"""电脑网站支付的表单存成数据 `payment_form = {action, fields}`,不再存一整段 HTML(`payment_html`)。

桌面端此前把那段自动提交的 HTML 塞进 `<iframe srcDoc>` 执行 —— srcdoc 和应用同源,服务端下发的脚本带着应用的权限在跑。
现在桌面端用自己的表单提交进 iframe。已有的单从 HTML 里解出 `action` 和隐藏字段;解不出的(本来就只在待付款的半小时里有用)留空。

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-14
"""

from __future__ import annotations

import html
import json
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
_ACTION = re.compile(r'<form[^>]*\baction="([^"]*)"')
_FIELD = re.compile(r'<input[^>]*\bname="([^"]*)"[^>]*\bvalue="([^"]*)"')


def _form_of(page: str) -> dict[str, object] | None:
    action = _ACTION.search(page)
    if action is None:
        return None
    return {"action": html.unescape(action.group(1)),
            "fields": {html.unescape(name): html.unescape(value) for name, value in _FIELD.findall(page)}}


def _page_of(form: dict[str, object]) -> str:
    fields = "".join(f'<input type="hidden" name="{html.escape(str(k), quote=True)}" value="{html.escape(str(v), quote=True)}">'
                     for k, v in dict(form.get("fields") or {}).items())
    return ('<!doctype html><html><head><meta charset="utf-8"></head><body>'
            f'<form action="{html.escape(str(form["action"]), quote=True)}" method="post">{fields}</form>'
            '<script>document.forms[0].submit()</script></body></html>')


def upgrade() -> None:
    op.add_column("cloud_orders", sa.Column("payment_form", JSONType, nullable=True))
    connection = op.get_bind()
    orders = sa.table("cloud_orders", sa.column("id", sa.String), sa.column("payment_html", sa.Text),
                      sa.column("payment_form", JSONType))
    for order_id, page in connection.execute(sa.select(orders.c.id, orders.c.payment_html)
                                             .where(orders.c.payment_html.is_not(None))).all():
        form = _form_of(page)
        if form is not None:
            connection.execute(orders.update().where(orders.c.id == order_id).values(payment_form=form))
    with op.batch_alter_table("cloud_orders") as batch:
        batch.drop_column("payment_html")


def downgrade() -> None:
    op.add_column("cloud_orders", sa.Column("payment_html", sa.Text(), nullable=True))
    connection = op.get_bind()
    orders = sa.table("cloud_orders", sa.column("id", sa.String), sa.column("payment_html", sa.Text),
                      sa.column("payment_form", JSONType))
    for order_id, form in connection.execute(sa.select(orders.c.id, orders.c.payment_form)
                                             .where(orders.c.payment_form.is_not(None))).all():
        value = json.loads(form) if isinstance(form, str) else form
        connection.execute(orders.update().where(orders.c.id == order_id).values(payment_html=_page_of(value)))
    with op.batch_alter_table("cloud_orders") as batch:
        batch.drop_column("payment_form")
