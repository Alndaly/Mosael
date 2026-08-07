"""连接的端点地址只给能改它的人看。

连接是**部署级**配置:只有部署管理员建得了、改得了。但它的 `base_url` 此前发给每一个登录用户 ——
设置页那一行下面就印着完整地址。

而端点地址常常是**身份**。真实撞到的一条:
`https://llm-i8gke1ymtjt99i4n.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` —— 中间那段是
阿里云百炼的专属部署标识。一个刚注册、还没配任何钥匙的新成员,一进设置页就拿到了它。私有部署的
内网地址、自建代理的域名、区域端点,都是同一类东西。

密钥早就分级了(别人的钥匙这里取不到,自己的也只回尾四位),端点没有 —— 因为它"看起来不像
秘密"。判据不该是"像不像秘密",而是**他能不能改它**:改不了却看得见,只有泄露没有用处。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from tests.util import add_provider, fresh_client, second_client

PRIVATE = "https://llm-i8gke1ymtjt99i4n.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


def _connection() -> str:
    with SessionLocal() as db:
        profile = add_provider(
            db, name="百炼qwen", vendor="alibaba", base_url=PRIVATE,
            api_key="k", model="qwen-max", capability_ids=["chat"], make_default=False,
        )
        db.commit()
        return profile.id


def test_a_member_does_not_get_the_endpoint() -> None:
    fresh_client()
    _connection()
    mate = second_client("mate")

    listed = mate.get("/api/settings/providers")

    assert listed.status_code == 200, listed.text
    assert PRIVATE not in listed.text, "端点原样发给了改不了它的人"
    assert "i8gke1ymtjt99i4n" not in listed.text


def test_a_deployment_admin_still_sees_it() -> None:
    """改得了就看得见 —— 藏起来会让管理员没法确认自己配的是哪个端点。"""
    admin = fresh_client()
    _connection()

    listed = admin.get("/api/settings/providers")

    assert PRIVATE in listed.text, listed.text


def test_the_member_still_gets_what_he_needs() -> None:
    """遮的是端点,不是整条连接:名字、厂商、能力、我自己钥匙的状态,一样不少。

    他要靠这些选模型、配自己的钥匙 —— 遮多了就变成"这里有个东西但不告诉你是什么"。
    """
    fresh_client()
    _connection()
    mate = second_client("mate")

    row = next(item for item in mate.get("/api/settings/providers").json() if item["name"] == "百炼qwen")

    assert row["vendor"] == "alibaba"
    assert "chat" in row["capability_ids"]
    assert row["is_mine"] is False, "他还没配自己的钥匙"


def test_endpoint_shaped_extras_are_covered_too() -> None:
    """`extra` 里也放着端点(自建代理、区域端点、图像生成 endpoint),一并遮。

    只遮 base_url 而漏掉这些,等于把同一件事做了一半 —— 而漏的那一半没有任何东西会报错。
    """
    fresh_client()
    with SessionLocal() as db:
        add_provider(
            db, name="自建", vendor="alibaba", base_url="https://public.example/v1",
            extra={"dashscope_base_url": PRIVATE}, api_key="k", model="qwen-max",
            capability_ids=["chat"], make_default=False,
        )
        db.commit()
    mate = second_client("mate")

    assert PRIVATE not in mate.get("/api/settings/providers").text
