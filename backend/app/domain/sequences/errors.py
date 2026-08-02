"""序列域的错误类型 —— 一个不认识任何人的叶子模块。

单独拆出来,是为了让 undo/ 那一组逆操作不必为了一个异常类型去 import 那个 1600 行的
operations 模块。抛错是它们唯一的共同需求,而依赖的粗细决定了以后谁能被单独测、单独改。
(和 app/domain/plugins/errors.py 同一个理由。)
"""

from __future__ import annotations


class SequenceDomainError(ValueError):
    pass
