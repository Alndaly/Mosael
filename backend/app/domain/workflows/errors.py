"""工作流领域错误。单独一个模块:节点表、图规则、增删改和执行器都要抛它,而它不该拖着 2000 行节点表一起被 import。"""

from __future__ import annotations

from typing import Any


class WorkflowDomainError(RuntimeError):
    """可安全展示给工作流操作者的领域错误。

    ``details`` 是给任务事件/历史界面的结构化诊断，不拼进短错误文案。这样列表仍然可读，
    同时失败现场（例如 LLM 的真实响应）不会在异常跨过执行线程时被丢掉。

    **第一个参数可以是 i18n 的 key,也可以是一句现成的话** —— 和任务消息那条路同构
    (见 domain/jobs.say):认得出 key 就按读的人的语言翻,认不出就当字面量原样用。
    失败原因会落库(Job.error_key / error_params),所以翻译发生在**读的时候**,而不是写的时候:
    写入时翻会把语言冻死在那一刻,用户切成英文后历史任务里的失败原因仍是中文。

    报错文本里的数据走 `params`,不要拼进句子 —— 拼进去那句话就只有一种语言了。
    """

    def __init__(self, message: str, *, params: dict[str, Any] | None = None,
                 details: dict[str, Any] | None = None) -> None:
        from app.core.i18n import DEFAULT_LOCALE, is_message_key, render_message, stored_param

        #: **只有认得出的才是 key。** 此前无条件记成 key,于是十几处 `WorkflowDomainError(str(exc))`
        #: 把第三方报错原文当 key 落了库(见 core/i18n.is_message_key)。
        self.key = message if is_message_key(message) else ""
        self.message = message
        #: 参数里的文案片段(如 field_name 给的字段名)原样留着,渲染时按读的人的语言翻。
        self.params = {k: stored_param(v) for k, v in (params or {}).items()}
        #: args 里放的是**缺省语言**那一句:pickle、repr 之类不经过 __str__ 的地方读它。
        super().__init__(render_message(message, DEFAULT_LOCALE, self.params))
        self.details = details or {}

    def __str__(self) -> str:
        """按**当时**的语言说 —— 和 LocalizedError 一样取 ContextVar。

        执行线程里没有请求语言,取到的就是缺省语言(日志、落库的 `error` 都读它,和此前一样);
        而编辑器里同步报的那些(图操作、导入文件)是在请求里抛的,路由拿 str(exc)
        当 detail,此前永远给缺省语言 —— 英文界面里弹出一句中文。
        """
        from app.core.i18n import get_current_locale, render_message

        return render_message(self.message, get_current_locale(), self.params)

    @classmethod
    def from_error(cls, exc: BaseException, *, details: dict[str, Any] | None = None) -> WorkflowDomainError:
        """把别的领域的错误转述成工作流错误,**带着它的 key 和参数**。

        此前各执行器写的是 `WorkflowDomainError(str(exc))`:那一刻就把话翻成了字,key 丢了,
        落库的失败原因从此只有写下它那一刻的语言(执行线程里就是缺省语言)。别的领域的错误
        改成 LocalizedError 之后,这条路是它们的 key 走进任务失败原因的唯一通道。
        认不出 key 的(第三方库的原话)照旧当字面量。
        """
        from app.core.i18n import is_message_key

        # 别的领域带着的失败现场(如「这一版要主人认可」的 attest,见 domain/authority)跟着走。
        if details is None and isinstance(getattr(exc, "details", None), dict):
            details = dict(exc.details)  # type: ignore[attr-defined]
        key = str(getattr(exc, "key", "") or "")
        if is_message_key(key):
            return cls(key, params=dict(getattr(exc, "params", None) or {}), details=details)
        return cls(str(exc), details=details)


# 节点类型注册表:同时驱动后端校验、前端节点面板和智能体的图编辑提示。
# outputs 是节点执行后写入上下文的键;config 描述每个可配置字段。
#: 配置项可以标 `"advanced": True`。
#:
#: 判据是「留空也能把这个节点跑起来吗」——能,就是高级项。编辑器把它们收进折叠的「高级选项」,
#: 不在用户第一眼就把十几个采样参数糊到脸上;AI 助手也读同一份声明,不会替用户瞎填。
#: 反过来:required 的、以及决定这个节点在做什么的字段(提示词、模型、URL),永远留在外面。
