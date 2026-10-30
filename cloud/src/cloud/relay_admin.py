"""官方中转的运维命令(ADR 0088 第 2 步:还没接支付,套餐、模型目录、上游通道都由维护者手动开通)。

    uv run python -m cloud.cli channel-key                                  生成一把 CLOUD_CHANNEL_KEY
    uv run python -m cloud.cli plan-set --slug pro --name Pro --period month --monthly-credits 20000 --credit-ttl-days 60 \\
        --price 29                                                          在线售价 ¥29(不给 = 只由管理员开通)
    uv run python -m cloud.cli subscribe --email a@b.com --plan pro         开通(当场发第一批月度积分)
    uv run python -m cloud.cli gift --email a@b.com --credits 500 --days 30 --note 内测
    uv run python -m cloud.cli model-set --id deepseek-chat --label "DeepSeek V3" --max-output-tokens 8000
    uv run python -m cloud.cli price-set --model deepseek-chat --input-per-1k 2 --output-per-1k 8
    CLOUD_UPSTREAM_KEY=sk-… uv run python -m cloud.cli channel-add --model deepseek-chat \\
        --base-url https://api.deepseek.com/v1 --upstream-model deepseek-chat --priority 0
    uv run python -m cloud.cli channel-list
    uv run python -m cloud.cli balance --email a@b.com

**上游 Key 不走命令行参数**(会进 shell 历史和进程列表):从 `CLOUD_UPSTREAM_KEY` 读,没有就在终端里问。
"""

from __future__ import annotations

import argparse
import getpass
import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.domain import admin, catalog, credits
from cloud.domain.channel_keys import new_channel_key
from cloud.mfa import new_fernet_key
from cloud.payments.base import cents_from_yuan, yuan
from cloud.models import (
    CloudGatewayModel,
    CloudPlan,
    CloudUpstreamChannel,
    CloudUpstreamProvider,
    CloudUser,
    new_id,
    now,
)


class AdminError(Exception):
    """命令没法做:说清为什么,命令以 2 退出。"""


def register(commands: argparse._SubParsersAction) -> None:
    key = commands.add_parser("channel-key", help="生成一把新的 CLOUD_CHANNEL_KEY(上游 Key 的落库加密钥)")
    key.set_defaults(relay=_channel_key, needs_db=False)

    mfa_key = commands.add_parser("mfa-key", help="生成一把新的 CLOUD_MFA_KEY(TOTP secret 的落库加密钥)")
    mfa_key.set_defaults(relay=lambda _args, _config, _db: new_fernet_key(), needs_db=False)

    plan = commands.add_parser("plan-set", help="新建或修改一个套餐")
    plan.add_argument("--slug", required=True)
    plan.add_argument("--name", required=True)
    plan.add_argument("--period", required=True, choices=sorted(credits.PERIOD_MONTHS))
    plan.add_argument("--monthly-credits", required=True, type=int)
    plan.add_argument("--credit-ttl-days", required=True, type=int)
    plan.add_argument("--price", help="在线售价,元(如 29 或 29.90);不给 = 不在线卖,只由管理员开通")
    plan.add_argument("--off-sale", action="store_true", help="下架(已订的不受影响)")
    plan.set_defaults(relay=_plan_set)

    subscribe = commands.add_parser("subscribe", help="给一个账号开通套餐(当场发第一批月度积分)")
    subscribe.add_argument("--email", required=True)
    subscribe.add_argument("--plan", required=True, help="套餐的 slug")
    subscribe.set_defaults(relay=_subscribe)

    gift = commands.add_parser("gift", help="赠送一批积分")
    gift.add_argument("--email", required=True)
    gift.add_argument("--credits", required=True, type=int)
    gift.add_argument("--days", required=True, type=int, help="有效天数")
    gift.add_argument("--note", default="")
    gift.set_defaults(relay=_gift)

    model = commands.add_parser("model-set", help="新增模型或按系统 ID 修改;新增时 ID 由系统生成")
    model.add_argument("--id", help="已存在模型的系统 ID;新建时留空")
    model.add_argument("--label", required=True)
    model.add_argument("--max-output-tokens", required=True, type=int)
    model.add_argument("--sort", type=int, default=0)
    model.add_argument("--disable", action="store_true")
    model.set_defaults(relay=_model_set)

    model_list = commands.add_parser("model-list", help="列出模型:系统 ID 与展示名")
    model_list.set_defaults(relay=_model_list)

    price = commands.add_parser("price-set", help="给模型定积分单价(加一行,带生效时间;不改旧价)")
    price.add_argument("--model", required=True)
    price.add_argument("--input-per-1k", required=True, type=int)
    price.add_argument("--output-per-1k", required=True, type=int)
    price.add_argument("--from", dest="effective_from", help="生效时间(ISO,UTC),缺省立即")
    price.set_defaults(relay=_price_set)

    provider = commands.add_parser("provider-add", help="新建上游供应商账号(Key 从 CLOUD_UPSTREAM_KEY 或终端读)")
    provider.add_argument("--name", required=True)
    provider.add_argument("--base-url", required=True, help="OpenAI 兼容端点前缀,如 https://api.deepseek.com/v1")
    provider.add_argument("--note", default="")
    provider.set_defaults(relay=_provider_add)

    provider_list = commands.add_parser("provider-list", help="列出上游供应商(不显示 Key)")
    provider_list.set_defaults(relay=_provider_list)

    channel = commands.add_parser("channel-add", help="给模型加一条上游通道(引用已有供应商)")
    channel.add_argument("--model", required=True)
    channel.add_argument("--provider", required=True, help="供应商 id")
    channel.add_argument("--upstream-model", required=True, help="上游那边这个模型叫什么")
    channel.add_argument("--priority", type=int, default=0, help="小的先用")
    channel.add_argument("--note", default="")
    channel.set_defaults(relay=_channel_add)

    listing = commands.add_parser("channel-list", help="列出上游通道(不显示 Key)")
    listing.set_defaults(relay=_channel_list)

    admin_grant = commands.add_parser("admin-grant", help="把已有账号设为 MosaelCloud 管理员")
    admin_grant.add_argument("--email", required=True)
    admin_grant.set_defaults(relay=_admin_grant)

    admin_revoke = commands.add_parser("admin-revoke", help="撤销一个 MosaelCloud 管理员(不能撤掉最后一名)")
    admin_revoke.add_argument("--email", required=True)
    admin_revoke.set_defaults(relay=_admin_revoke)

    admin_list = commands.add_parser("admin-list", help="列出 MosaelCloud 管理员")
    admin_list.set_defaults(relay=_admin_list)

    balance = commands.add_parser("balance", help="看一个账号此刻的积分")
    balance.add_argument("--email", required=True)
    balance.set_defaults(relay=_balance)


def _user(db: Session, email: str) -> CloudUser:
    user = db.scalar(select(CloudUser).where(CloudUser.email == email.strip().lower()))
    if user is None:
        raise AdminError(f"没有这个账号:{email}")
    return user


def _channel_key(_args, _config: CloudConfig, _db: Session | None) -> str:
    return new_channel_key()


def _plan_set(args, _config: CloudConfig, db: Session) -> str:
    if args.monthly_credits <= 0 or args.credit_ttl_days <= 0:
        raise AdminError("每月积分和有效天数都要大于 0")
    plan = db.scalar(select(CloudPlan).where(CloudPlan.slug == args.slug))
    if plan is None:
        plan = CloudPlan(slug=args.slug)
        db.add(plan)
    plan.name = args.name
    plan.period = args.period
    plan.monthly_credits = args.monthly_credits
    plan.credit_ttl_days = args.credit_ttl_days
    plan.on_sale = not args.off_sale
    try:
        plan.price_cents = cents_from_yuan(args.price) if args.price else None
    except ValueError as exc:
        raise AdminError(f"--price 要是元为单位的金额,如 29 或 29.90:{args.price}") from exc
    if plan.price_cents == 0:
        raise AdminError("--price 要大于 0;不在线卖就别给 --price")
    price = f",在线售价 ¥{yuan(plan.price_cents)}" if plan.price_cents else ",不在线卖"
    return f"套餐 {args.slug}:{args.name},{args.period},每月 {args.monthly_credits} 积分,每批有效 {args.credit_ttl_days} 天{price}"


def _subscribe(args, _config: CloudConfig, db: Session) -> str:
    plan = db.scalar(select(CloudPlan).where(CloudPlan.slug == args.plan))
    if plan is None:
        raise AdminError(f"没有这个套餐:{args.plan}")
    user = _user(db, args.email)
    subscription = credits.subscribe(db, user, plan, at=now())
    left = credits.balance(db, user.id, at=now()).total
    return f"{user.email} 已开通 {plan.name},到 {subscription.ends_at:%Y-%m-%d};当前积分 {left}"


def _gift(args, _config: CloudConfig, db: Session) -> str:
    if args.credits <= 0 or args.days <= 0:
        raise AdminError("积分和天数都要大于 0")
    user = _user(db, args.email)
    credits.gift(db, user, amount=args.credits, days=args.days, note=args.note, at=now())
    return f"已送 {user.email} {args.credits} 积分,{args.days} 天内有效"


def _model_set(args, _config: CloudConfig, db: Session) -> str:
    if args.max_output_tokens <= 0:
        raise AdminError("--max-output-tokens 要大于 0")
    model_id = args.id or new_id()
    model = catalog.upsert_model(
        db,
        model_id=model_id,
        label=args.label,
        kind="chat",
        max_output_tokens=args.max_output_tokens,
        enabled=not args.disable,
        sort_order=args.sort,
    )
    labels = catalog.display_labels(db.scalars(select(CloudGatewayModel)).all())
    return (
        f"模型 {model.id}({labels.get(model.id, model.label)}),一次最多 {model.max_output_tokens} token,"
        f"{'停用' if args.disable else '启用'}"
    )


def _model_list(_args, _config: CloudConfig, db: Session) -> str:
    rows = db.scalars(
        select(CloudGatewayModel).order_by(
            CloudGatewayModel.sort_order, CloudGatewayModel.label, CloudGatewayModel.created_at, CloudGatewayModel.id
        )
    ).all()
    if not rows:
        return "还没有模型"
    labels = catalog.display_labels(rows)
    return "\n".join(
        f"{one.id}  {labels.get(one.id, one.label)}  {'启用' if one.enabled else '停用'}"
        for one in rows
    )


def _price_set(args, _config: CloudConfig, db: Session) -> str:
    if args.input_per_1k < 0 or args.output_per_1k < 0:
        raise AdminError("单价不能是负数")
    if db.get(CloudGatewayModel, args.model) is None:
        raise AdminError(f"目录里没有这个模型:{args.model}(先 model-set)")
    effective = datetime.fromisoformat(args.effective_from) if args.effective_from else now()
    catalog.set_price(db, model_id=args.model, input_per_1k=args.input_per_1k, output_per_1k=args.output_per_1k,
                      effective_from=effective)
    return f"{args.model}:每千输入 {args.input_per_1k}、每千输出 {args.output_per_1k} 积分,{effective:%Y-%m-%d %H:%M} 起"


def _provider_add(args, config: CloudConfig, db: Session) -> str:
    if not config.channel_key:
        raise AdminError("没配 CLOUD_CHANNEL_KEY:先 `channel-key` 生成一把、写进部署配置,再加供应商")
    if not args.base_url.startswith(("https://", "http://")):
        raise AdminError("--base-url 要是 http(s) 地址")
    api_key = os.environ.get("CLOUD_UPSTREAM_KEY", "").strip() or getpass.getpass("上游 API Key:").strip()
    if not api_key:
        raise AdminError("没拿到上游 API Key")
    provider = catalog.add_provider(
        db, config, name=args.name, base_url=args.base_url, api_key=api_key, note=args.note
    )
    return f"供应商 {provider.id}:{provider.name} → {provider.base_url}"


def _provider_list(_args, _config: CloudConfig, db: Session) -> str:
    rows = db.scalars(select(CloudUpstreamProvider).order_by(CloudUpstreamProvider.name)).all()
    if not rows:
        return "还没有上游供应商"
    return "\n".join(
        f"{one.id}  {one.name}  {one.base_url}  {'启用' if one.enabled else '停用'}"
        for one in rows
    )


def _channel_add(args, config: CloudConfig, db: Session) -> str:
    if db.get(CloudGatewayModel, args.model) is None:
        raise AdminError(f"目录里没有这个模型:{args.model}(先 model-set)")
    provider = db.get(CloudUpstreamProvider, args.provider)
    if provider is None:
        raise AdminError(f"没有这个供应商:{args.provider}(先 provider-add)")
    channel = catalog.add_channel(
        db,
        model_id=args.model,
        provider_id=args.provider,
        upstream_model=args.upstream_model,
        priority=args.priority,
        note=args.note,
    )
    return f"通道 {channel.id}:{args.model} → {provider.name}/{args.upstream_model},优先级 {args.priority}"


def _channel_list(_args, _config: CloudConfig, db: Session) -> str:
    rows = db.execute(
        select(CloudUpstreamChannel, CloudUpstreamProvider)
        .join(CloudUpstreamProvider, CloudUpstreamProvider.id == CloudUpstreamChannel.provider_id)
        .order_by(CloudUpstreamChannel.model_id, CloudUpstreamChannel.priority)
    ).all()
    if not rows:
        return "还没有上游通道"
    at = now()
    return "\n".join(
        f"{channel.id}  {channel.model_id}  p{channel.priority}  {provider.name}  ({channel.upstream_model})"
        f"  {'启用' if channel.enabled else '停用'}"
        f"{'  冷却到 ' + f'{channel.cooldown_until:%H:%M:%S}' if channel.cooldown_until and channel.cooldown_until > at else ''}"
        f"{'  ' + channel.note if channel.note else ''}"
        for channel, provider in rows
    )


def _admin_grant(args, _config: CloudConfig, db: Session) -> str:
    user = _user(db, args.email)
    changed = admin.grant(db, user)
    return f"{user.email} {'已成为' if changed else '已经是'} MosaelCloud 管理员"


def _admin_revoke(args, _config: CloudConfig, db: Session) -> str:
    user = _user(db, args.email)
    try:
        changed = admin.revoke(db, user)
    except admin.RoleError as exc:
        if exc.code == "last_admin":
            raise AdminError("不能撤销最后一名管理员;先授予另一个账号") from exc
        raise
    return f"{user.email} {'已撤销管理员' if changed else '本来就不是管理员'}"


def _admin_list(_args, _config: CloudConfig, db: Session) -> str:
    users = admin.admins(db)
    if not users:
        return "还没有 MosaelCloud 管理员"
    return "\n".join(f"{user.email or user.phone or user.id}  @{user.handle or '-'}" for user in users)


def _balance(args, _config: CloudConfig, db: Session) -> str:
    user = _user(db, args.email)
    current = credits.balance(db, user.id, at=now())
    lines = [f"{user.email}:{current.total} 积分" + (f",套餐 {current.plan_name}" if current.plan_name else "")]
    lines += [f"  {one.remaining}({one.source},{one.expires_at:%Y-%m-%d} 到期)" for one in current.batches]
    if current.next_grant_at:
        lines.append(f"  下一批 {current.next_grant_at:%Y-%m-%d}")
    return "\n".join(lines)

