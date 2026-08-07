"""令牌在库里长什么样 —— 一个纯函数,不碰数据库。

单独一个模块,是因为**两边都要用它而它们不能互相认识**:铸造与校验在 core/security,
把老库里的明文就地换掉的迁移在 core/db,而 core/security 要用 db.models、db.models 又依赖
core/db —— 让 core/db 去 import core/security 就成了环(见 tests/test_import_layering)。
哈希本身不需要认识这两边的任何一边。
"""

from __future__ import annotations

import hashlib

#: 库里那一列的形状前缀。**必须带前缀**:原始令牌本身就是 64 位十六进制(token_hex(32)),
#: 和裸哈希长得一模一样,没有前缀就没法判断某一行迁过没有 —— 而迁移每次启动都会跑,认错一次
#: 就是把所有人哈希两遍、全部掉线。
TOKEN_SCHEME = "sha256"


def token_digest(raw: str) -> str:
    """令牌存进库时的样子。

    **存哈希,不存原文,也不加密。** 令牌就是这个人本人 —— 拿到它等于拿到他的一切,而且不需要
    密码、不留痕迹。校验时把来客手上那串再哈希一次比对即可,根本不需要把原文取回来;而能取回
    原文的方案(对称加密)只是把问题挪到"主密钥放哪",在同一台机器上尤其没有意义。密码早就是
    这个待遇了,令牌此前不是。

    不加盐:令牌是 256 位随机数,没有字典可查,加盐只会让"按令牌查行"变成全表扫描。
    """
    return f"{TOKEN_SCHEME}:{hashlib.sha256(raw.encode()).hexdigest()}"
