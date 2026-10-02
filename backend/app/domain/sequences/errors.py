"""序列域的错误类型 —— 一个不认识任何人的叶子模块。

单独拆出来,是为了让 undo/ 那一组逆操作不必为了一个异常类型去 import 那个 1600 行的
operations 模块。抛错是它们唯一的共同需求,而依赖的粗细决定了以后谁能被单独测、单独改。
(和 app/domain/plugins/errors.py 同一个理由。)
"""

from __future__ import annotations

from app.core.i18n import LocalizedError


class SequenceDomainError(LocalizedError, ValueError):
    """时间线说不行。带文案 key(`seqErr_*`),按请求方的语言翻;认不出的 key 原样显示。
    `status` 由子类给,边界照着翻 —— 不从翻译过的句子里猜(中文请求里没有 "not found")。"""

    status = 422


class SequenceNotFound(SequenceDomainError):
    """这条时间线不存在。"""

    status = 404


class SequenceChangedElsewhere(SequenceDomainError):
    """调用方以为时间线停在某一版,它却已经在别处被改过(剪辑页、智能体、另一个人)。这时照「最新的一步」撤,
    撤掉的就不是他以为的那一步 —— 拒掉,让他去看一眼。"""

    status = 409


class SequenceRevisionConflict(SequenceDomainError):
    """这一步是照着某一版时间线做的,而时间线已经被别人(另一个人、智能体、画板、自己的另一个窗口)改到了
    别的样子,和这一步对不上 —— 照做就是在一份过时的时间线上替人做决定。拒掉,边界把最新的那一版一起交回去,
    让他看着现状再做(见 concurrency)。

    `who` 是改了它的那些人(文案片段的列表,按读的人的语言连起来);`base_revision` 是调用方以为的那一版。"""

    status = 409

    def __init__(
        self, key: str, *, base_revision: int | None = None, current_revision: int | None = None, **params: object
    ) -> None:
        super().__init__(key, **params)
        self.base_revision = base_revision
        self.current_revision = current_revision
