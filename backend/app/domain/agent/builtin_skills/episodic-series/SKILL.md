---
name: episodic-series
description: "做连续剧 / 漫剧:系列设定建角色(带嗓子)与场景,按场并行出片,盯进度、断了接着跑。"
metadata:
  mosael-title: "做连续剧"
---

# 做连续剧 / 漫剧

工具:`list_workflow_templates`、`create_workflow`(带 `template_id`)、`run_workflow`(带 `runs` 并行)、
`get_workflow_run`、`continue_workflow_run`、`list_entities` / `set_entity_voice`、`list_speech_engines`。

## 1. 先定系列设定(一次)

1. `create_workflow(template_id="series_setup")` 建一张「连续剧 · 系列设定」。
2. `run_workflow` 的 `params`:`title`、`premise`(必填);`episodes` 集数;`characters` / `locations` 一行一个,
   用户说了的角色、场景、想要的嗓子都写进去,没说的留空让模型按梗概补;`style` 画风。
3. 跑完:分集大纲存成笔记,每个角色有三视图和一把嗓子、每个场景有设定图,都在资产库里(`list_entities` 看)。
   用户想换哪个角色的嗓子,用 `list_speech_engines` 挑一把,`set_entity_voice` 改。

**角色和场景的名字就是钥匙**:后面每一集按名字到资产库里认,同一张脸、同一把嗓子。不要改名。

## 2. 一集拆成几场,每场一次「从主题到完整视频」

- 一场 10–20 镜(每镜几秒由开始节点的 `shot_seconds` 定),一集 5–10 分钟就是 4–6 场。
- 每场的 `topic` 写成**逐镜的分场剧本**:一行一镜,写画面、谁说话、台词原文;要求「逐字照用,不增不减」。
  台词写成角色名 + 台词,旁白单独标出 —— 配音按说话的角色找他的嗓子,旁白用开始节点那一把。
- 同一张「从主题到完整视频」可以一次并行跑几场:`run_workflow(workflow_id, runs=[{场1 参数}, {场2 参数}, …])`,
  一张卡批完,交回每场一个 job_id。`max_shots`、`target_duration_seconds` 按每场镜数填。

## 3. 盯进度、断了接着跑

- 一场要跑很久(每镜一张首帧 + 一段视频)。隔一阵 `get_workflow_run(job_id)` 看:做完了哪几步、子任务成败、失败原因、
  花了多少。**不要连着刷**,一次看完再等。
- 失败或中断了(`can_continue: true`):先看 `recent_failures` 的原因,能修的先修(换模型、补连接),再
  `continue_workflow_run(job_id)` —— 做完的步骤不再做、不再花钱。
- 四场都完了,把每场导出的成片接成一集(时间线工具 `edit_timeline`),需要时整集再铺一首配乐。
