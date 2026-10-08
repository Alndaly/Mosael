"""后端自己的多语言。

**为什么不是"后端发 key、前端翻"**:后端这些文案的消费者不止前端 —— 智能体的工具返回、
飞书机器人推的消息、任务中心的通知标题、失败原因文本,都不经过前端的 messages.ts。
发 key 会让它们变成一串 `publishOpt_visibility`,比现在糟。

**语言从哪来**:这是个多租户、可远程部署的后端,没有"服务端语言"这回事 —— 每个消费者都得
拿到自己的那一种。按优先级:请求头 Accept-Language → (将来)用户偏好 → 部署默认 zh。
飞书/定时任务这类**没有请求上下文**的场景走后两条。

**文案存 key、出口翻译**:领域里的目录(平台、引擎…)存 key,序列化那一层才翻。这样
PLATFORM_OPTIONS 这种被后端校验、前端渲染、执行器消费的表不必知道语言。
"""

from __future__ import annotations

from contextvars import ContextVar
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# 语言清单、「这一次是谁在问」那个 ContextVar、数据自带文案的挑法,和插件包 / 工作流文件校验报错的
# 文案,都住在 mosael_formats(桌面后端与社区服务共用的格式包,ADR 0026)。这里接过来用同一份:
# 同一个 ContextVar,格式包里的 FormatError 说哪种语言就和这里的 LocalizedError 一致。
from mosael_formats.i18n import (
    CURRENT_LOCALE,
    DEFAULT_LOCALE,
    LOCALES,
    MESSAGES as FORMAT_MESSAGES,
    pick_text as pick_text,
)

from app.core import messages as _messages

#: key → {语言: 文案}。**每个 key 两种语言都必须有**(见 tests/test_backend_i18n.py 的棘轮)。
#: 格式包自己的那几条(插件清单 / 插件包 / 工作流文件的校验报错)并进来,`t()`、`is_message_key`、
#: `LocalizedError.relay` 才认得它们;不在这张表里再抄一份 —— 两份会漂。其余按领域分片在 core/messages。
MESSAGES: dict[str, dict[str, str]] = _messages.merged(FORMAT_MESSAGES, *(part.MESSAGES for part in _messages.PARTS))


#: 本次请求的语言。由中间件按 Accept-Language 设定(见 app/main.py)。
#:
#: **为什么要有它**:任务消息由 12 个接口返回,若在每个路由里各取一次请求头再翻,就是同一个问题
#: 十二个答案 —— 漏一个,那一屏的任务就还是另一种语言。序列化那一层拿不到 Request,ContextVar 是
#: 让它知道"这一次是谁在问"的唯一办法。
#: 没有请求上下文时(飞书机器人、定时任务、后台线程)取缺省 —— 那正是它该给的答案。
_current_locale: ContextVar[str] = CURRENT_LOCALE


def set_current_locale(locale: str) -> None:
    _current_locale.set(locale)


def get_current_locale() -> str:
    return _current_locale.get()


@contextmanager
def speaking(locale: str | None) -> Iterator[None]:
    """在这一段里按 `locale` 说话 —— 后台线程替发起的人说他的语言(工作流运行时生成的那几句:用的是哪把嗓子、
    口播收紧了哪几段……)。线程不继承上下文变量,不设的话一律落成缺省语言。出了这一段恢复原样(线程会被复用)。"""
    token = CURRENT_LOCALE.set(normalize_locale(locale) if locale else DEFAULT_LOCALE)
    try:
        yield
    finally:
        CURRENT_LOCALE.reset(token)


def normalize_locale(raw: str | None) -> str:
    """把 Accept-Language 归一成我们支持的那几种。

    只取主语言标签(`zh-CN` → `zh`),不认的一律回落到缺省 —— **不猜**:与其把 `ja` 硬映射到
    某种语言,不如给缺省,至少它是一致的。
    """
    for part in (raw or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        primary = tag.split("-")[0]
        if primary in LOCALES:
            return primary
    return DEFAULT_LOCALE


def _drop_placeholders(text: str) -> str:
    """把填不上的占位符连同它的标点一起抹掉,只留字面部分。

    退路不能是「原样返回模板」:那样用户脸上就糊着一个 `{name}`。而这条路真正会被走到的
    是**旧任务记录** —— message_params 这一列是后加的,它之前落库的那些行参数是空的,
    而接口按 key 重翻。给一个 key 补上占位符(「工作流失败」→「工作流失败: {name}」)时,
    历史行就都走这里:抹掉之后它们回到补占位符之前的样子,正是当初存进去的那句。
    """
    from string import Formatter

    literals = [literal for literal, field, _, _ in Formatter().parse(text) if literal]
    # 占位符没了,它前面那个引导标点也就没有要引导的东西了。
    return "".join(literals).strip().rstrip(":：,，、-—").strip()


def is_message_key(text: str) -> bool:
    """这是**我们自己的一条文案 key**,还是一句现成的话?

    任务消息(`jobs.say`)和工作流错误(`WorkflowDomainError`)都接受"key 或一句话"——两者共用
    一个参数,于是必须有**一个**地方判断到底是哪一种,而不是各处各猜。判据只有一条:在不在
    MESSAGES 里。认不出的就是字面量:原样显示,**不当模板填**,也**不当 key 落库**。

    这一条是付过账才收进来的:第三方报错原文(LLM 返回的 403 JSON)被当成 key 截成 80 字存进
    `error_key`,读的时候又拿它当模板去 format —— 花括号一炸,整个执行历史接口 500,
    而面板上什么都不说,看起来就是"一次运行都没有"。
    """
    return text in MESSAGES


def _text(key: str, locale: str) -> str:
    """这条 key 在这个语言下的原文。**查不到就原样返回 key**,不抛错:一条文案缺翻译不该让整个
    接口 500。它会以 key 的样子出现在界面上——难看,但看得见,而棘轮保证它进不了主干。"""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    return entry.get(locale) or entry.get(DEFAULT_LOCALE) or key


def t(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    """翻一个 key,可带参数。

    带参数的句子(「安装 {engine} 运行依赖…」)是模板 —— **参数在产生它的地方就算好、跟着 key 一起
    传出来**,而不是把值直接拼进句子。拼进去就没法翻了:那句话从此只有一种语言。

    **没传参数就原样返回,不跑 format。** 界面文案里的花括号是**给人照抄的写法**,不是待填的槽:
    节点提示里的 `{{转写.segments}}` 正是用户要往输入框里敲的那串字,而 format 会把它吃掉一层
    花括号,照抄下去不生效;`{名: 值}` 这种示例更惨——它会被当成一个填不上的槽整段抹掉
    (「{名: 引用},如 …」曾经在界面上只剩下一个",如")。
    任务消息那条路要的正相反(槽填不上就该消失),走 render_message。
    """
    text = _text(key, locale)
    if not params:
        return text
    try:
        return text.format(**_resolve_params(params, locale))
    except (KeyError, IndexError, ValueError):
        return _drop_placeholders(text)


def fragment(key: str, **params: Any) -> Any:
    """摘要里被拼进去的**那半句**,留成 key 而不是当场翻成字。

    确认卡的措辞是拼出来的(「给 *12 条字幕* 配音 *,并变速压回原段落长度*」),而拼进去的
    每一段自己也是文案。当场翻的话,外层就算存了 key,内层还是冻成了写它那天的语言。

    返回的是一个带 `__key` 的小字典,渲染(`t` / `render_message`)时递归展开 —— 它落进
    JSON 列(确认卡的 `summary_params`、任务的 `error_params`),所以形状必须是能 JSON 化的。

    报错里提到的字段名也是这种半句:「{field} 必须是整数」里的 field 在中文界面叫「条数上限」、
    英文界面叫「Limit」。当场翻成字塞进参数,外层句子按读的人的语言翻了,里面那半截还是写它
    那天的语言。
    """
    return {"__key": key, "params": params} if key else ""


def authored_text(value: Any) -> Any:
    """**别人写好的**一句话(插件运行时交回的失败原因),它可以按语言分着给:`{"zh": …, "en": …}`。

    和 `fragment` 是一对:那个是我们自己的文案 key,这个是数据自带的翻译(写法和插件清单里给人看的文字一样,
    挑法见 pick_text)。按语言分的那份**原样留着**、包成一个带 `__text` 的小字典,渲染时再按读的人挑 ——
    它会落进 JSON 列(连接的出错原因),而写下它的那一刻(后台刷新、另一种界面语言)不是读它的人的语言。

    一个字符串就是那句话本身(只说一种语言的插件);一句话都没有的回空串。
    """
    if isinstance(value, dict):
        texts = {str(lang): one for lang, one in value.items() if isinstance(one, str) and one.strip()}
        return {"__text": texts} if texts else ""
    return str(value) if value else ""


def stored_param(value: Any) -> Any:
    """一个参数落库(JSON 列)前的形状:文案片段、按语言分的话和列表原样留着,读的时候再翻、再挑、
    再按读的人的习惯连起来(见 _resolve_params);其余写成字。"""
    if isinstance(value, dict) and ("__key" in value or "__text" in value):
        return value
    if isinstance(value, (list, tuple)):
        return [stored_param(one) for one in value]
    return str(value)


def read_param(value: Any, locale: str) -> Any:
    """一个留着没翻的参数(文案片段 `fragment`、按语言分的话 `authored_text`、它们的列表)按这个语言读成字;别的原样。"""
    if isinstance(value, dict) and "__key" in value:
        return render_message(str(value["__key"]), locale, value.get("params") or {})
    if isinstance(value, dict) and "__text" in value:
        return pick_text(value["__text"], locale)
    if isinstance(value, list):
        # **连接号也随语言变**:中文用顿号,英文用逗号加空格。先翻每一段,再按读的人的
        # 习惯连起来 —— 反过来(先连再翻)得到的是一串翻不动的拼接物。
        return _text("punct_listSep", locale).join(str(read_param(one, locale)) for one in value)
    return value


def _resolve_params(params: dict[str, Any] | None, locale: str) -> dict[str, Any]:
    """参数里带 `__key` 的那些(见 fragment)先各自按这个语言渲染、带 `__text` 的(见 authored_text)
    按这个语言挑一句,再交给外层去填。"""
    return {name: read_param(value, locale) for name, value in (params or {}).items()}


def render_message(key: str, locale: str = DEFAULT_LOCALE, params: dict[str, Any] | None = None) -> str:
    """渲染一条**任务消息**:占位符必须被填掉,填不上就连同标点一起抹掉(见 _drop_placeholders)。

    和 t() 分家,是因为两类文案对花括号的期待正相反:任务消息里的 `{name}` 是待填的槽,没有参数
    就该消失;而界面文案里的花括号是要给人看的写法,碰都不该碰。此前两者共用一条路,于是给任务
    消息补占位符的那次改动,顺手把三条节点提示打成了残句。
    """
    #: 认不出的 key 是一句现成的话,不是模板 —— 它里面的花括号是内容(JSON、代码),不是槽。
    #: 拿它去 format,要么抛错、要么把 `{"error": …}` 当占位符抹掉(见 is_message_key)。
    if not is_message_key(key):
        return key
    text = _text(key, locale)
    try:
        return text.format(**_resolve_params(params, locale))
    except (KeyError, IndexError, ValueError):
        return _drop_placeholders(text)


def tr(key: str, **params: object) -> str:
    """按**这次请求**的语言翻一个 key(语言由中间件放进 ContextVar,见 app/api/middleware)。

    路由里直接写的报错(HTTPException 的 detail)用它;领域错误用 LocalizedError。
    """
    return t(key, get_current_locale(), **params)


class LocalizedError(Exception):
    """带文案 key 的错误:领域里只说「是哪一种」和参数,**不拼句子**;变成文字时按当时的语言翻。

    `str(exc)` 取的是 ContextVar 里的语言 —— 在请求里就是请求方的语言,在后台线程里是缺省语言。
    所以各领域那些「`{"detail": str(exc)}`」的出口不用改,换成它就自动跟着界面语言走。

    此前 Blender、插件等领域的报错是写死的中文句子:英文界面里弹出来的是中文,中间还夹着上游
    原样透传的英文(「Blender 未完成同步:Error executing code: Could not connect to Blender…」)。
    上游给的原文作为参数(通常叫 `detail`)放进翻好的句子里,不在领域里拼接。
    """

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return t(self.key, get_current_locale(), **self.params)

    @classmethod
    def relay(cls, exc: BaseException) -> "LocalizedError":
        """把别的领域的错误转述成这一类,**带着它的 key 和参数**。

        此前各处写的是 `XxxError(str(exc))`:上游那句话在抛出那一刻就翻成了字,key 丢了 ——
        落进任务失败原因、接口 detail 的只剩写下它那一刻的语言。认不出 key 的(第三方库的原话)
        照旧当字面量:`t` 查不到就原样返回那句话。
        """
        key = str(getattr(exc, "key", "") or "")
        if is_message_key(key):
            return cls(key, **dict(getattr(exc, "params", None) or {}))
        return cls(str(exc))


#: 状态字典里放模板参数的那一栏。翻完就摘掉 —— 它是给翻译用的,不该出现在 API 响应里。
PARAMS_FIELD = "message_params"


def translate_fields(payload: dict[str, Any], keys: tuple[str, ...], locale: str) -> dict[str, Any]:
    """把一个字典里指定的几个字段就地翻掉(返回新字典,不改原数据)。

    `message` 这一栏如果带模板参数(见 PARAMS_FIELD),用它来格式化,然后把参数栏摘掉。
    """
    params = payload.get(PARAMS_FIELD) or {}
    out = {
        **payload,
        **{
            # message 是任务消息,填不上的槽要抹掉;其余字段是界面文案,原样翻。
            k: (render_message(payload[k], locale, params) if k == "message" else t(payload[k], locale))
            for k in keys
            if isinstance(payload.get(k), str)
        },
    }
    out.pop(PARAMS_FIELD, None)
    return out
