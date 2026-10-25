# ADR 0083 · 飞书里的选择卡：复用 AgentQuestion，单选/多选/自由文本都在飞书完成

- 状态：**Accepted** — 2026-10-25。飞书对话原来只能收文字、发确认卡；`ask_user` 在 Mosael
  里有选择题，但飞书侧看不到。现在把同一组问题推进飞书，答案仍落 `AgentQuestion`。
- 相关：ADR 0044（会话归属）、ADR 0065（飞书触发工作流）、ADR 0070（飞书绑定按应用）、
  ADR 0081（Computer Use 的桌面回放）
- 代码：`backend/app/integrations/feishu/question_cards.py`、
  `backend/app/integrations/feishu/inbound.py`、`backend/app/integrations/feishu/approvals.py`、
  `backend/app/domain/agent/origins.py`、`backend/app/domain/agent/use_cases.py`

## 要解决什么

`ask_user` 是模型在岔路口把两三条路摊给用户挑的能力，支持：

- 单选（`multi_select: false`）
- 多选（`multi_select: true`）
- 每题 2–6 个选项，最多 4 题
- 「其他」自由文本，可跳过

在 Mosael 里这些字段已经有 UI；飞书会话却没有推送问题的通路。飞书用户看不到题，答案也就无从产生。

## 决定

1. **问题仍然只有一个事实源**：`AgentQuestion`。飞书卡片不另建问题表、不复制答案状态；
   卡片提交后走和 Mosael 完全相同的 `agent.use_cases.answer/dismiss`。
2. **开问题卡走外部来源钩子**：`ExternalOrigin.question_opened` 和确认卡的
   `confirmation_opened` 同形；领域层不认识飞书，飞书在 `inbound.py` 登记推送实现。
3. **卡片用一张 form 收集全部问题**：单选用 `select_static`，多选用
   `multi_select_static`，每题一个可选自由文本 `input`；一次 `form_submit` 提交整组答案。
   飞书回调已经把 `form_value` 和按钮 `value` 一起送来，`approvals.handle_card_action`
   按动作名把问题回调分流到 `question_cards.handle_card_action`。
4. **自由文本覆盖选择**：同一题填了「其他」就只用自由文本；空着才用选择。单选在飞书这一侧
   也校验只能选一个。
5. **授权沿用绑定**：点击者按 `(workspace, bot, open_id)` 找 Mosael 成员，且仍须有该会话的
   写权限；未绑定/无权限只回 toast，原卡保持可点。

   **无主的飞书群聊会话不能按私人会话判。** 飞书会话没有 `owner_user_id`，`ask_user` 起初走普通
   `writable_session`，于是创建问题时就回 `Not found`，卡片根本没机会发出。现在问题域复用确认卡
   的规则：有主人走 readable/writable；无主人只要求调用人仍是工作区成员（写问题再要 `ai` 权限）。
6. **回答后卡就地换成结果态**：`已提交` 列出每题选择，`已跳过` 表示跳过；同一张卡再点会得到
   “已经处理过了”。问题卡不需要保存 message id。
7. **等用户操作时摘掉 `Typing`，等完贴回。** 选择卡和确认卡都会让这一轮停在等人的状态，
   正常收尾不会跑；如果只在 `turn_finished` 摘反应，用户会一直看到“智能体正在回复”。
   sidecar 的 `awaiting_user(waiting)` 是准确信号：`true` 时摘掉当前消息的反应，`false`
   时贴回去；作答、跳过、超时继续生成都走同一对事件，回合收尾再统一摘掉。
8. **不改变飞书确认卡**：工具确认仍是同意/拒绝；工作流审批仍是同意/拒绝 + 可选备注。问题卡
   和它们是同一回调入口的不同动作。
9. **卡片按整行铺满**：题目、下拉、输入框各占一整行；跳过/提交是两个等宽列里的 `fill`
   按钮，合起来占满一行，不在右侧留一块空白。
10. **作答是条件更新，不是读后写**：`AgentQuestion.status = 'pending'` 是 CAS 条件；重复回调
    只有赢得更新的那一次会 `deliver_to_session`，跳过也一样。否则两次点击会变成两条
    “我选好了”的用户消息，再起两轮模型。

## 后果

- 飞书对话现在可以完成 Mosael 里的同一套选择；答案回到原会话并唤醒等待中的智能体。
- 多选卡片要求飞书客户端 7.4+；旧客户端会显示升级提示，这是飞书表单组件的版本边界。
- 问题卡发送失败不阻止问题落库；飞书侧降级发一句「请在 Mosael 回答」，不丢问题。
- 已有绑定、工作区权限、跳过、自由文本长度限制都继续生效；没有为了飞书放宽授权。
