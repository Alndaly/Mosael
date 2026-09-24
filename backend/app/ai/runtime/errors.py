"""本机引擎(装运行环境、下权重、常驻 worker)说不行的那一句。

带文案 key(`runtimeErr_*`,见 core/i18n),`str(exc)` 按读的人的语言翻:在请求里就是请求方的
语言,在安装线程里是缺省语言。装不上的原因要落到状态卡片上(`InstallProgress` /
`DownloadProgress` 的 message + params),那里**存 key 和参数、出口再翻** —— 见 `failure_message`。
"""

from __future__ import annotations

from app.core.i18n import LocalizedError, is_message_key


class RuntimeSetupError(LocalizedError, RuntimeError):
    """运行环境装不上、权重下不来、worker 没做成。

    仍然是 RuntimeError:调用方(路由、任务)原本就按 RuntimeError 接,换成它不必改那一头。
    """


def failure_message(exc: BaseException, *, limit: int = 400) -> tuple[str, dict[str, str]]:
    """一个异常 → 状态卡片上那句话:`(key 或原话, 参数)`。

    带 key 的(LocalizedError)记 key 和参数,出口(`translate_fields`)按读的人的语言翻;
    不带的(pip、git、第三方库)只有它自己的那句话,原样截断 —— 那是它的文本,我们翻不了。
    """
    key = str(getattr(exc, "key", "") or "")
    if isinstance(exc, LocalizedError) and is_message_key(key):
        return key, {name: str(value) for name, value in exc.params.items()}
    return str(exc)[:limit], {}


def venv_failure(output: str) -> RuntimeSetupError:
    """`python -m venv` 没建成。挑得出原因(core/text.blame_line)就带上;挑不出就直说没留下原因
    —— 这半句也跟着语言走,所以是另一条 key,不是一个写死的中文兜底串。"""
    from app.core.text import blame_line

    detail = blame_line(output)
    return RuntimeSetupError("runtimeErr_venvFailed", detail=detail) if detail else RuntimeSetupError("runtimeErr_venvFailedSilent")


def with_log(message: str, params: dict[str, str], log: object | None) -> tuple[str, dict[str, str]]:
    """失败原因后面补一句「完整日志:<路径>」。

    不把这半句拼进原因里:拼进去它就只剩一种语言了。有 `…Log` 变体的 key 用变体;原话(子进程
    自己说的那句)套进 `runtimeErr_failedWithLog`;别的 key 没有变体就原样返回。
    """
    from app.core.i18n import MESSAGES

    if log is None:
        return message, params
    if is_message_key(message):
        variant = f"{message}Log"
        return (variant, {**params, "log": str(log)}) if variant in MESSAGES else (message, params)
    return "runtimeErr_failedWithLog", {"detail": message, "log": str(log)}
