# ADR 0033 · 插件工具只有一种:宿主开放服务,插件注册自己的工具

- 状态:已采纳(2026-09-30,维护者:「MinerU 这类插件的工具本身是要在智能体和工作流的工具表里开放的」「宿主开放部分能力
  让插件自身的工具注册,而不是插件走宿主」)
- 取代:ADR 0032 §3「只经宿主」与它「不做」里的第一条
- 相关:ADR 0020(插件做生成供应商)、ADR 0031(文档解析能力)、`domain/plugins/inputs`(素材进)、`domain/plugins/artifacts`(文件出)

## 背景

ADR 0032 把宿主能力做成了一张表,每一项都能由插件注册实现;但认领了能力的工具被一律藏起来(`internal`),理由是它们
说的是「宿主协议」:宿主先把文件拷进暂存目录、把路径塞进 payload(`invoke_host` 的 `prepare`),插件交回暂存目录里的
相对路径,宿主在目录删掉之前取走(`collect`)。于是插件页上出现了两种工具 —— 能勾、能进智能体和工作流的普通工具,和一张
「由 Mosael 调用」的卡片 —— 而 MinerU 这个插件自己的工具在它自己的工具表里是灰的。

但那套「宿主协议」里的每一件事,普通工具早就有了,只是走的是另一条路:

| 宿主协议里的一步 | 普通工具已有的那条 |
| --- | --- |
| `prepare`:把文件拷进暂存目录给插件 | `format: "asset"` 的入参:宿主把素材换成暂存目录里的一份副本(`inputs.materialize`) |
| `collect`:插件交回相对路径,宿主取走 | `artifact` / `artifacts` 出参:宿主把文件收进素材库(`artifacts.register`) |
| 流式进度、取消文件 | `stream: true`:普通调用同样走 `stream_tool`,进度报给任务总线 |

两条路做的是同一件事,只是一条对插件作者和使用者都不可见。

## 决定

### 1. 插件工具只有一种

认领了能力的工具**照样是一个注册进工具表的普通工具**:插件页上有勾、智能体和工作流节点面板里点得到、画板上能用,开不开
由用户定(清单的 `expose` / `recommended` 给初值)。`internal` 只剩两处:

- 清单(或 `overrides`)显式标了 `internal` 的 —— Blender 的原始代码执行入口这一类;
- **目录类能力** `generation`、`tools`:认领它们的工具回答的是「这个连接有哪些模型 / 哪些工具」,本身不是一次能交给人的
  调用(模型和工具各自出现在该出现的地方)。

`HOST_ONLY_CAPABILITIES` 拆成 `CATALOG_CAPABILITIES = {generation, tools}`(仍不开放)和其余的**调用类能力**
(`document_parse`、`audio_denoise`、`audio_separation`、`transcription`、`translation`、`speech`)。

### 2. 宿主开放的是服务,插件在自己工具的 schema 里点名用哪项

| 服务 | 插件怎么点名 | 宿主做什么 |
| --- | --- | --- |
| 素材进 | 入参 `format: "asset"`;`x-media`(限定素材类型,节点上本来就认它)与新增的 `x-audio` | 给副本;`x-media` 让表单只列这几种、调用时核对;`x-audio: original` 先抽成原采样率的 wav,`speech` 抽成 16k 单声道 wav |
| 文件出 | 出参 `artifact` / `artifacts` | 收进素材库,换成 `asset_id` |
| 进度与取消 | `stream: true` | 进度报给任务总线,取消先让插件去停远端的活 |
| 能力的收尾 | 工具上的 `provides: [X]` | 见 3(只有需要落到宿主数据上的能力才有) |

没有第二套协议:插件作者学一遍工具怎么写,就会写能力的实现。

### 3. 能力是加在工具上的一份契约;不管谁调,走同一条路、同一个收尾

认领能力 X 的工具,入参 / 出参必须用上面的服务按 X 的契约声明(装的那一刻检查,和今天「恰好一个工具认领」同一处)。
**调用只有一条路**(`tools.invoke`):智能体、工作流节点、画板、插件页「试一下」、宿主自己的入口(文档「重新解析」、降噪按钮……)
都是「用某个素材调这个工具」。宿主手上的文件不在素材库里时(转写前抽好的音轨、时间线上截的一段),经同一个素材入参交,
同一道暂存。

产出分两种去处:宿主的入口握着自己的落点(那一行解析、那条字幕轨、放回视频),在暂存目录删掉之前自己取走(`collect`);
智能体、工作流、插件页「试一下」调它时,产出按通用规矩收(`artifact` 进素材库、别的原样交回)—— 只有结果要落到宿主数据上的
能力登记一个**收尾**(能力表 `Capability.finish`),替通用调用方把产出放到该放的地方。今天只有文档解析有:

| 能力 | 入参契约 | 出参契约 | 收尾 |
| --- | --- | --- | --- |
| `document_parse` | `file`:asset,`x-media` 含 document | `markdown`:暂存目录里带段标记的 Markdown,插图在 `images/` | 存成那份文档的一次新解析(和「重新解析」同一个落点),交回 `asset_id`、段数 |
| `audio_denoise` | `file`:asset,`x-media` 含 audio、video,`x-audio: original` | `artifact`:处理好的音频 | 无(`artifact` 成新素材) |
| `audio_separation` | 同上 | `artifacts`:`output: vocals` / `background` | 无(两份新素材) |
| `transcription` | `file`:asset,`x-media` 含 audio、video,`x-audio: speech`;可选 `language` | `segments`(起止、文字,可带说话人与词级时间) | 无(分段原样交回) |
| `translation` | `texts`(数组)、`target`;可选 `source` | `texts` | 无(原样交回) |
| `speech` | `op`(`voices` / `speak`) | `voices` 或 `artifact`(一段音频) | 无(音频经 `artifact` 成素材) |

两条入口跑的是同一段(`tools._run_process`:暂存、注入、跑子进程、落 state)。`invoke_host` 仍是宿主入口用的那一个(失败抛异常、
`collect` 取走产出、`files` 交手上的文件);`prepare` 只剩目录类的生成在用 —— 它的输入是一串带角色的文件,不是工具入参里的素材格子。

### 4. 插件页只有一张工具表

「由 Mosael 调用」那一块并进工具表:认领了能力的那一行多一枚能力徽标(「文档解析」),展开里除了试跑表单,还有能力表现算的
「也用在」(ADR 0032 §4 那份)。

## 迁移

- 清单:随包的 MinerU 改成契约形状(1.3.0);已装的第三方包的清单经清单迁移链改写(`MANIFEST_VERSION` 4)—— 认领调用类能力的
  工具,素材入参补上 `format: asset` 与契约里的 `x-media` / `x-audio`;
- 出参的变化(降噪、分离、配音改交 `artifact`)在插件代码里,清单改不了;仓库里没有实现它们的真插件(只有测试替身),替身随契约改;
- 连接上的工具开关按清单的 `recommended` / `expose` 补(随包插件启动对账时 `seed_capabilities`);
- API:实例上的 `host_tools` 去掉,这些工具在 `tools` 里,多 `provides` 与 `used_by`;插件页的「由 Mosael 调用」那一块并进工具表。

## 不做

- 不开放目录类能力(`generation`、`tools`)的那个工具;
- 不给 MCP 插件认领调用类能力:素材进、文件出这两项服务只有进程插件有(MCP 是别人的协议,和今天一样)。
