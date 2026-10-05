---
name: workflow-canvas
description: "搭和改工作流画布的做法:先想清楚形状(并排、子图、调用别的工作流),再用 edit_workflow 一步步改。用户要新建工作流、改工作流里的节点和连线、把一串步骤做成能反复跑的流程时,先读它。"
metadata:
  mosael-title: "搭工作流"
---

# 搭工作流

工具是 `get_workflow` / `list_workflow_node_types` / `edit_workflow`(新建用 `create_workflow`,跑用 `run_workflow`)。

## 改之前

1. `get_workflow` 读最新的图;不确定某种节点收什么,用 `list_workflow_node_types` 查。
2. 一次 `edit_workflow` 只装一个连贯的改动 —— 它会开一张确认卡,用户批准后才落地。
3. 删除节点用 `edit_workflow` 的 `remove_node`,**不要**用 `edit_timeline`(那是视频时间线的工具)。
   start / 开始节点也可以删;删了之后工作流存成草稿,运行前要重新加回 start。

## 先想清楚形状再动手

工作流不止能画一条直线:

- **互不依赖的几步就让它们并排** —— 同一个节点接出多条边,引擎会并发跑,总时长按最慢的那支算。
  串成一条直线是白等。典型:同时生成三张图、同时查三个来源。
- **一段复杂但只用一次的流程,用 `subgraph`(子图)折起来**:它在节点里嵌一整张子画布,外层看到的就是一个节点。
  画布二十个节点连成一片时,读的人分不清哪几步是一件事。
- **一段会被别处复用的流程,抽成独立工作流,再用 `call_workflow` 调它。** 复制粘贴出来的两份改一处就得改两处,
  而这正是它们开始不一样的那一刻。

## 改完

告诉用户你提交了什么、在等哪张确认卡;批准之后要跑就 `run_workflow`,结果回来再说明产出在哪。
