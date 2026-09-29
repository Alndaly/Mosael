from __future__ import annotations

import functools
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text, TypeDecorator

logger = logging.getLogger(__name__)

"""密钥不明文落盘。

一个库文件 = 所有人的钥匙,而库文件**很容易离开这台机器**:备份、iCloud/Time Machine、磁盘镜像、
更名迁移留下的 `.stale`、发给支持人员的一份拷贝。加密挡的就是这一类泄露。

**挡不住什么也要说清**:拿得到主机、读得到进程环境的人照样解得开 —— 密钥必须能被这个进程读到。
所以这不是"加密了就安全",而是把「库文件泄露」和「主机被拿下」分成两件不同后果的事。

主密钥**不放在库里**(同一个文件里的钥匙和锁等于没锁),按顺序取:

    标准输入                  桌面版:Electron 用系统钥匙串封存主密钥(electron/master-key.cjs),起后端时
                              设 MOSAEL_SECRET_KEY_STDIN=1、从标准输入交第一行。**不走环境变量**:同一个系统
                              用户的其他进程(插件)读得到另一个进程的环境变量;数据目录里也就没有明文密钥。
    MOSAEL_SECRET_KEY    环境变量 —— 服务端部署的答案(systemd EnvironmentFile、docker
                              secret、k8s secret)。
    <数据目录>/secret.key      0600 的文件 —— 裸跑 uvicorn、或系统没有可用钥匙串时的兜底。它只挡"库文件单独
                              泄露",挡不住"整个数据目录被拷走";这是如实的降级,不是等价方案。

需要同一把密钥的子进程(飞书连接)由 `child_handoff` 给出怎么交:密钥是从标准输入来的,就照样经它的
标准输入交下去。

加解密挂在**列类型**上(见 EncryptedText/EncryptedJSON),领域代码一行都不用改 —— 也就没有
"这里记得解密、那里忘了"的可能。
"""

ENV_VAR = "MOSAEL_SECRET_KEY"
#: 设为 1 = 主密钥在标准输入的第一行(桌面版,见模块说明)。读到之后从本进程环境里摘掉,子进程不继承。
STDIN_FLAG = "MOSAEL_SECRET_KEY_STDIN"
KEY_FILENAME = "secret.key"

#: 装秘密的列。**登记在这一处**,棘轮据此检查它们确实用了加密类型
#: (见 tests/test_secrets_at_rest.py)。新加一个装秘密的列而忘了加密,测试直接红。
ENCRYPTED_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("provider_credentials", "api_key"),
        ("provider_credentials", "oauth_credential"),
        ("provider_credentials", "secrets"),
        ("plugin_credentials", "value"),
        ("feishu_bots", "app_secret"),
        ("publish_accounts", "config"),
    }
)


def key_path() -> Path:
    from app.core.config import settings

    return settings.data_dir / KEY_FILENAME


#: 主密钥从哪来的(stdin / env / file),`child_handoff` 据此决定怎么交给子进程。
_source = ""
_lock = threading.Lock()


def _from_stdin() -> bytes:
    """读标准输入的第一行。只读一次(`master_key` 缓存),读完从环境里摘掉标记,子进程不会再去读它们的 stdin。"""
    line = sys.stdin.buffer.readline() if sys.stdin is not None else b""
    os.environ.pop(STDIN_FLAG, None)
    key = line.strip()
    if not key:
        raise RuntimeError(f"{STDIN_FLAG}=1,但标准输入里没有主密钥")
    return key


@functools.lru_cache(maxsize=1)
def master_key() -> bytes:
    """这个部署的主密钥:标准输入(桌面版)> 环境变量 > 数据目录里的 0600 文件(没有就建一个)。

    缓存:每读一次列都去碰一次文件系统没有意义,而"密钥是哪一把"在一次进程生命周期里不变。
    测试换密钥时调 `master_key.cache_clear()`。加锁:第一次取可能同时来自几条线程,而标准输入只能读一次。
    """
    with _lock:
        return _load()


def _load() -> bytes:
    global _source
    if os.environ.get(STDIN_FLAG) == "1":
        _source = "stdin"
        return _from_stdin()
    supplied = (os.environ.get(ENV_VAR) or "").strip()
    if supplied:
        _source = "env"
        return supplied.encode()

    _source = "file"
    path = key_path()
    if path.is_file():
        return path.read_bytes().strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    generated = Fernet.generate_key()
    # 先建成 0600 再写内容:先写后 chmod 会留下一个短暂的全局可读窗口。
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "wb") as file:
        file.write(generated)
    logger.info("生成了新的落盘加密密钥:%s(请随数据目录一起备份 —— 丢了就解不开已存的凭据)", path)
    return generated


def child_handoff() -> tuple[dict[str, str], str | None]:
    """要用同一把主密钥的子进程怎么拿到它:(要加的环境变量, 要写进它标准输入的一行)。

    密钥是从标准输入来的(桌面版)就照样经子进程的标准输入交下去;环境变量、文件两种情况子进程照同一条路
    自己取,什么都不用给。"""
    key = master_key()
    if _source == "stdin":
        return {STDIN_FLAG: "1"}, key.decode() + "\n"
    return {}, None


def encrypt(plaintext: str) -> str:
    return Fernet(master_key()).encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str | None:
    """解不开就回 None —— 调用方据此当作「没配置」。

    **fail closed**:密钥换了或丢了的时候,把一段密文当成 API Key 发到供应商的端点上,比报一句
    「请先配置密钥」坏得多。
    """
    try:
        return Fernet(master_key()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        logger.error("解不开一份落盘的凭据:主密钥换了或丢了(见 core/secrets_at_rest)")
        return None


def looks_encrypted(value: str) -> bool:
    """这串是不是本模块加密出来的。

    只在**迁移**里用,用来分辨老库里的明文与已经加密过的密文;运行时不做这种判断 —— 那就成了
    读取期的两路兼容,而那正是 ADR 0006 要避免的。
    """
    if not value.startswith("gAAAAA"):
        return False
    try:
        Fernet(master_key()).decrypt(value.encode())
    except (InvalidToken, ValueError):
        return False
    return True


class EncryptedText(TypeDecorator):
    """落盘加密的字符串列。空串不加密(它不是秘密,加密只会让"没配"看起来像"配了")。"""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None or value == "":
            return value
        return encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None or value == "":
            return value
        plain = decrypt(str(value))
        return "" if plain is None else plain


class EncryptedJSON(TypeDecorator):
    """落盘加密的 JSON 列。形状与 JSON 列一致,只是盘上是一串密文。"""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return encrypt(json.dumps(value, ensure_ascii=False))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None or value == "":
            return None
        plain = decrypt(str(value))
        if plain is None:
            return None
        try:
            return json.loads(plain)
        except ValueError:
            return None
