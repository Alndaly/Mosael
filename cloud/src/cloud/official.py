"""官方内容 = **官方账号发布的分享**。

维护者裁决:插件和工作流本身就是分享,官方插件 / 官方工作流就是官方账号发布的分享。
所以这里没有第二套表、没有第二套 payload:

- 官方账号是 `cloud_users` 里 `official = true` 的那一行;
- 官方分享就是同一张 `cloud_shares` 里的普通行,`kind` 用 `plugin` / `workflow`,
  `owner_user_id` 指向官方账号。

**只有这个模块会写 `official = true`。** 注册接口与 `PUT /me` 都不认识这个字段(测试钉住)。

官方账号**可以正常登录**:它是一个由部署方持有的运营账号,不是"内容占位符"。

- handle / email 来自 `CLOUD_OFFICIAL_HANDLE` / `CLOUD_OFFICIAL_EMAIL`(有缺省),**只在建号时**使用;
  已存在的账号不会被改写(和标题 / payload 一样守住"只补缺");
- 密码来自 `CLOUD_OFFICIAL_PASSWORD`。设了就**每次种子都写成这个值** —— 这是对"只补缺"的
  唯一例外,理由见 `_ensure_official_user`;没设就不动密码(新账号因此没有密码,密码登录 401,
  这不是错误)。密码短于 `password_min_length` 会在配置构造时直接失败(见 `cloud.config`)。
- 邮箱验证码对官方号**正常投递**,登录限流也照常生效;没有"官方号专用"的旁路。

种子命令: `python -m cloud.cli seed-official --bundle <path.json>`

幂等键用 bundle 里的稳定 `slug` + 语言:

- 标题是给人改的 —— 运营改一次标题,按标题去重就会在下一次部署产出第二条;
- slug 是发布方的稳定标识,Git 里的 bundle 改了标题也不会变;
- 同一条内容的 `zh-CN` / `en-US` 是**两行**,payload 相同、标题 / 简介各取自己的语言;
- 唯一索引 `(owner_user_id, kind, slug, locale)` 让并发 / 重复执行在数据库层也最多一行。

**只补缺,不覆盖**:已存在的行(按 owner + kind + slug + locale)整行跳过,标题 / 简介 / payload /
许可都不动;用户自己的分享没有 slug,永远不会被种子碰到。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud.db import Database
from cloud.domain.shares import (
    HUMAN_PAYLOAD_LIMIT,
    MAX_LICENSE,
    MAX_PAYLOAD_BYTES,
    MAX_SUMMARY,
    MAX_TITLE,
    SHARE_LOCALES,
    create_share,
    payload_bytes,
)
from cloud.errors import CloudError
from cloud.models import CloudShare, CloudUser
from cloud.security import hash_password

#: 缺省短名。它在 `identity.RESERVED_HANDLES` 里,普通用户注册不到。
OFFICIAL_HANDLE = "mosael"
OFFICIAL_DISPLAY_NAME = "Mosael 官方"
#: 固定头像种子:官方头像的颜色不随部署漂移。
OFFICIAL_AVATAR_SEED = "mosael-official"
#: 缺省邮箱。RFC 2606 保留的 `.example` 顶级域:公网 DNS 永远解析不到,所以它默认收不到信。
#: 部署方必须用 `CLOUD_OFFICIAL_EMAIL` 换成一个**真实拥有**的地址,验证码登录才可用。
OFFICIAL_EMAIL = "official@mosael.example"

#: bundle 顶层键 → 分享 kind。**只认这两个**:画板不是"官方发布内容"的一部分。
BUNDLE_LISTS = {"plugins": "plugin", "workflows": "workflow"}
#: 一条 bundle 内容可以带哪几种语言。和 `SHARE_LOCALES` 是同一组值,顺序决定插入顺序。
BUNDLE_LOCALES = SHARE_LOCALES
#: 一条内容允许的键。`title` / `summary` 必须放进 `locales`,不在顶层 —— 旧格式不兼容。
ENTRY_KEYS = frozenset({"slug", "locales", "license", "payload"})
LOCALE_TEXT_KEYS = frozenset({"title", "summary"})

MAX_SLUG = 80
#: slug 是稳定标识,只允许小写字母 / 数字 / `.` `_` `-`,且以字母或数字开头。
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class SeedError(ValueError):
    """bundle 或落库出了人该看见的问题。CLI 把它变成 stderr + 退出码 2。"""


@dataclass(frozen=True)
class SeedReport:
    account_created: bool
    handle: str = OFFICIAL_HANDLE
    created: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        parts = [
            f"官方账号 @{self.handle} "
            + ("已创建" if self.account_created else "已存在(补齐缺的字段)")
        ]
        for list_name, kind in BUNDLE_LISTS.items():
            parts.append(
                f"{list_name}: 新增 {self.created.get(kind, 0)} 行 / 已存在 {self.skipped.get(kind, 0)} 行"
            )
        return ";".join(parts)


def load_bundle(path: str | Path) -> dict[str, Any]:
    """读并整份校验 bundle。**先校验、后落库**:结构不对不会留下半个官方账号。"""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SeedError(f"读不到 bundle: {source}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SeedError(f"bundle 不是合法 JSON: {exc}") from exc
    check_bundle(data)
    return data


def check_bundle(data: Any) -> None:
    if not isinstance(data, dict):
        raise SeedError("bundle 顶层必须是一个 JSON 对象")
    unknown = sorted(set(data) - set(BUNDLE_LISTS))
    if unknown:
        raise SeedError(f"bundle 顶层有不认识的键: {', '.join(unknown)}")
    for list_name in BUNDLE_LISTS:
        entries = data.get(list_name, [])
        if not isinstance(entries, list):
            raise SeedError(f"`{list_name}` 必须是数组")
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            where = f"{list_name}[{index}]"
            if not isinstance(entry, dict):
                raise SeedError(f"{where} 必须是对象")
            unknown_keys = sorted(set(entry) - ENTRY_KEYS)
            if unknown_keys:
                raise SeedError(
                    f"{where}: 不认识的键: {', '.join(unknown_keys)}"
                    "(标题 / 简介请放进 `locales`,旧格式不再接受)"
                )
            slug = _clean_slug(entry.get("slug"), where)
            if slug in seen:
                raise SeedError(f"{where}: `{list_name}` 里 slug 重复: {slug}")
            seen.add(slug)
            _check_locales(entry.get("locales"), where)
            license_value = entry.get("license")
            if license_value is not None and not isinstance(license_value, str):
                raise SeedError(f"{where}: `license` 必须是字符串或 null")
            if isinstance(license_value, str) and len(license_value.strip()) > MAX_LICENSE:
                raise SeedError(f"{where}: `license` 超过 {MAX_LICENSE} 个字符")
            if "payload" not in entry or entry["payload"] is None:
                raise SeedError(f"{where}: `payload` 必填")
            try:
                size = payload_bytes(entry["payload"])
            except CloudError as exc:
                raise SeedError(f"{where}: `payload` 必须是一份 JSON") from exc
            if size > MAX_PAYLOAD_BYTES:
                raise SeedError(f"{where}: `payload` 超过 {HUMAN_PAYLOAD_LIMIT}")


def _check_locales(raw: Any, where: str) -> None:
    """`locales` 至少一种语言;只认 zh-CN / en-US;每种语言的标题必填、简介可选。"""
    if not isinstance(raw, dict) or not raw:
        raise SeedError(f"{where}: `locales` 必填,且至少要有一种语言(zh-CN / en-US)")
    unknown = sorted(set(raw) - set(BUNDLE_LOCALES))
    if unknown:
        raise SeedError(f"{where}: 不支持的语言: {', '.join(unknown)}(只支持 zh-CN / en-US)")
    for locale in BUNDLE_LOCALES:
        text = raw.get(locale)
        if text is None:
            continue
        place = f"{where}.locales[{locale}]"
        if not isinstance(text, dict):
            raise SeedError(f"{place} 必须是对象")
        unknown_keys = sorted(set(text) - LOCALE_TEXT_KEYS)
        if unknown_keys:
            raise SeedError(f"{place}: 不认识的键: {', '.join(unknown_keys)}")
        title = text.get("title")
        if not isinstance(title, str) or not title.strip():
            raise SeedError(f"{place}: `title` 必须是非空字符串")
        if len(title.strip()) > MAX_TITLE:
            raise SeedError(f"{place}: `title` 超过 {MAX_TITLE} 个字符")
        summary = text.get("summary")
        if summary is not None and not isinstance(summary, str):
            raise SeedError(f"{place}: `summary` 必须是字符串或 null")
        if isinstance(summary, str) and len(summary.strip()) > MAX_SUMMARY:
            raise SeedError(f"{place}: `summary` 超过 {MAX_SUMMARY} 个字符")


def _clean_slug(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise SeedError(f"{where}: `slug` 必填")
    value = raw.strip()
    if len(value) > MAX_SLUG or not SLUG_RE.fullmatch(value):
        raise SeedError(f"{where}: `slug` 只能用小写字母、数字和 . _ -,最长 {MAX_SLUG},且以字母或数字开头")
    return value


def seed_official(
    database_url: str,
    bundle: Mapping[str, Any],
    *,
    handle: str = OFFICIAL_HANDLE,
    email: str = OFFICIAL_EMAIL,
    password: str = "",
) -> SeedReport:
    """把 bundle 里的官方插件 / 工作流补进分享表。**幂等**:重复跑不新增行、不覆盖改动。

    `handle` / `email` / `password` 来自 `CLOUD_OFFICIAL_*`(见 `cloud.cli`)。语言按 bundle
    里实际有的发:只给 zh 就只发 zh 一行,不编造英文。
    """
    check_bundle(bundle)
    chosen_handle = (handle or "").strip()
    chosen_email = (email or "").strip().lower()
    if not chosen_handle:
        raise SeedError("官方账号的 handle 不能为空")
    if not chosen_email:
        raise SeedError("官方账号的 email 不能为空")

    database = Database(database_url)
    try:
        session = database.session()
        try:
            user, account_created = _ensure_official_user(
                session, handle=chosen_handle, email=chosen_email, password=password
            )
            created = {kind: 0 for kind in BUNDLE_LISTS.values()}
            skipped = {kind: 0 for kind in BUNDLE_LISTS.values()}
            for list_name, kind in BUNDLE_LISTS.items():
                for entry in bundle.get(list_name, []):
                    slug = _clean_slug(entry["slug"], list_name)
                    for locale in BUNDLE_LOCALES:
                        text = entry["locales"].get(locale)
                        if text is None:
                            # 这种语言 bundle 里没有:只发有的那一行,不编造标题。
                            continue
                        if _exists(session, user.id, kind, slug, locale):
                            skipped[kind] += 1
                            continue
                        if _create(
                            session,
                            user,
                            kind=kind,
                            slug=slug,
                            locale=locale,
                            title=text["title"],
                            summary=text.get("summary"),
                            entry=entry,
                        ):
                            created[kind] += 1
                        else:
                            # 唯一索引撞了:另一个进程刚刚写了同一行。当作"已存在"。
                            skipped[kind] += 1
            return SeedReport(
                account_created=account_created,
                handle=user.handle or chosen_handle,
                created=created,
                skipped=skipped,
            )
        finally:
            session.close()
    finally:
        database.dispose()


def _ensure_official_user(
    session: Session, *, handle: str, email: str, password: str
) -> tuple[CloudUser, bool]:
    """找到(或建立)官方账号,补上空字段,并按环境变量写密码。

    官方账号按**公开标记**认,不按 handle:运营把 `CLOUD_OFFICIAL_HANDLE` 改掉时,
    旧账号仍然是官方账号,不应该因此多建一个。没有官方标记时按配置的 handle 兼容
    "上一条种子写出来的行"。

    已存在时**只补空字段**(昵称 / 头像种子),不改邮箱、handle,也不动它已经发的东西。
    """
    user = session.scalar(
        select(CloudUser)
        .where(CloudUser.official.is_(True))
        .order_by(CloudUser.created_at, CloudUser.id)
        .limit(1)
    )
    if user is None:
        # 这个 handle 是保留字,能落在它上面的只可能是早先的种子输出。
        user = session.scalar(select(CloudUser).where(CloudUser.handle == handle))
    if user is not None:
        changed = False
        if not user.official:
            user.official = True
            changed = True
        if not user.display_name:
            user.display_name = OFFICIAL_DISPLAY_NAME
            changed = True
        if not user.avatar_seed:
            user.avatar_seed = OFFICIAL_AVATAR_SEED
            changed = True
        if password:
            # **对"只补缺"的唯一例外。** 标题 / 简介 / payload / handle / email 都不覆盖:
            # 它们是内容与身份,运营可能已经在库里手改过。密码不是内容,它只有一个来源 ——
            # 部署环境变量。不每次写回,运营改环境变量就永远改不了密码,轮换也无法完成。
            # 每次都重新 hash(新盐):语义就是"库里这行的密码等于当前环境变量的值"。
            user.password_hash = hash_password(password)
            changed = True
        if changed:
            session.commit()
        return user, False

    user = CloudUser(
        email=email,
        password_hash=hash_password(password) if password else None,
        email_verified_at=None,
        display_name=OFFICIAL_DISPLAY_NAME,
        handle=handle,
        avatar_seed=OFFICIAL_AVATAR_SEED,
        official=True,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SeedError(
            f"{email} 或 @{handle} 已经被另一个账号占用;官方账号没有建出来。"
            "先人工确认那个账号是谁,再决定是否手工处理。"
        ) from exc
    return user, True


def _exists(session: Session, owner_id: str, kind: str, slug: str, locale: str) -> bool:
    return (
        session.scalar(
            select(CloudShare.id).where(
                CloudShare.owner_user_id == owner_id,
                CloudShare.kind == kind,
                CloudShare.slug == slug,
                CloudShare.locale == locale,
            )
        )
        is not None
    )


def _create(
    session: Session,
    user: CloudUser,
    *,
    kind: str,
    slug: str,
    locale: str,
    title: str,
    summary: str | None,
    entry: Mapping[str, Any],
) -> bool:
    """走**和用户发布完全一样**的 `create_share`(标题 / 简介 / 2 MB 校验、同一 serializer)。

    返回 False 表示唯一索引撞上了(并发种子),不是错误。
    """
    try:
        create_share(
            session,
            user,
            kind=kind,
            locale=locale,
            title=title,
            summary=summary,
            payload=entry["payload"],
            license=entry.get("license"),
            slug=slug,
        )
    except IntegrityError:
        session.rollback()
        return False
    except CloudError as exc:
        session.rollback()
        raise SeedError(f"{kind} `{slug}` ({locale}): {exc.code}") from exc
    return True
