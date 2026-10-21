

def test_有备注时按钮必须放在_form_里且是_form_submit():
    """飞书的卡片 schema 是硬校验:form 里没有提交按钮,**整张卡**会被拒。

    真实错误(从 `feishu_delivery_reason` 读到的):
      `ErrCode: 300123, ErrPath: ROOT -> elements -> [3](tag: form),`
      `ErrMsg: there is no submit button in the form container`
    表现是"确认卡发不出去、只剩一段降级文字",而卡片开关、长连接、权限**全都是好的** ——
    所以这条要钉在 schema 上,不是钉在配置上。
    """
    from app.integrations.feishu import cards

    card = cards.approval_card(
        approval_id="ap-1", title="t", body="b", workflow="w", node="n",
        approve_label="确认", reject_label="拒绝", allow_note=True,
        timeout_hours=None,
    )
    form = next(element for element in card["elements"] if element.get("tag") == "form")
    submits = [one for one in form["elements"] if one.get("action_type") == "form_submit"]
    assert len(submits) == 2, "form 里必须有两个 form_submit(同意 / 拒绝),否则整张卡被飞书拒收"
    assert {one["value"]["action"] for one in submits} == {cards.ACTION_RUN_APPROVE, cards.ACTION_RUN_REJECT}
    #: **每个 form 按钮都要有 name** —— 缺了它整张卡仍被拒:
    #: `ErrCode: 200530, ErrPath: ROOT -> elements -> [3](tag: form) -> elements -> [1](tag: button),`
    #: `ErrMsg: name can not be empty string`
    assert all(one.get("name") for one in submits), "form 里的按钮缺 name,飞书会拒收整张卡"
    #: 不能既放 form 里又放外面 —— 外面再摆一份会出现四颗按钮。
    assert not any(one.get("tag") == "action" for one in card["elements"])


def test_没有备注时仍是普通按钮():
    from app.integrations.feishu import cards

    card = cards.approval_card(
        approval_id="ap-1", title="t", body="b", workflow="w", node="n",
        approve_label="确认", reject_label="拒绝", allow_note=False,
        timeout_hours=None,
    )
    assert not any(one.get("tag") == "form" for one in card["elements"]), "没备注就不该有 form"
    action = next(one for one in card["elements"] if one.get("tag") == "action")
    assert len(action["actions"]) == 2
    assert action["actions"][0]["value"]["action"] == cards.ACTION_RUN_APPROVE
