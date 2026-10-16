# ADR 0068:提示词里引用到的素材,以「参考图」并进生成节点的「输入素材」(带一道能力闸)

## Status

Accepted — 2026-10-16。ADR 0067 在**大模型节点**上定下「引用即发送」;这一笔把它照搬到
「AI 生成素材」(`ai_generate`)的 `source_assets`,并多一道**能力闸**:模型不收那个角色就不并。
维护者拍板:「提示词里 `@` 引用到图片时,自动同步进节点的『源素材』,角色默认『参考图』」,
而且要在**表单里看得见 / 改得动 / 删得掉**。

## Context

### 同一个断层,在生成节点上更贵

ADR 0067 的断层是:提示词里 `{{画图.asset_id}}` 只当**文字**插值,模型从没见过那张图。
`ai_generate` 上一样:那张图只有走 `source_assets` 才发得出去,用户得记得再挑一遍。

区别在代价。大模型节点那一格并进来的是「多带一张图」;生成节点这一格并进来的**每一份都带角色**,
而角色决定这次生成做什么:

| 角色 | 模型拿到它之后做的事 |
| --- | --- |
| `first_frame` 首帧 | 画面**从这一格开始动** |
| `reference_image` 参考图 | **照着它的风格和主体**来拍,它自己一帧都不出现在成片里 |
| `driving_audio` 驱动音频 | 画面跟着它走(口型、卡点) |

猜错角色不是"多一张图",是一次报错或者一次**白花钱的生成**(成片出来了,只是不是那件事)。
所以在 ADR 0067 那一笔里,这一处刻意**没动**(见 0067 的 Consequences:风险不同,留单独一笔)。

### 为什么不做成"编辑时同步进配置"

和 ADR 0067 逐字同一个理由,不重写第二遍:**值到运行时才知道**(上游可能还没跑),而老图的
config 里没有那一串 id —— 编辑时同步就必须再补一条「config 里没有就现推」的兼容分支,
同一条语义写两遍。这里只写一遍。

## Decision

### 1. 同一份声明、同一处推导,只在内存里

`source_assets` 上加的三个声明,和大模型节点的 `image_asset_ids` 是同一族:

```python
"ref_assets_from": ["prompt"],          # 提示词里引用到的素材并进这一格
"ref_assets_role": "reference_image",   # 并进来时以什么角色发(默认「参考图」)
"ref_assets_gate": "generation_source_role",   # 并之前先问一句「这个模型收不收这个角色」
```

唯一实现仍是 `binding.with_referenced_assets`(engine 在节点跑起来那一刻调一次)。
**派生集合只在内存、不写回库**:库里那份配置一个字节都不动,老图不用改任何东西
(`tests/test_ai_generate_sees_referenced_images.py::test_引用即发送是运行时推导_老图不用改配置`)。

并进来的每一份写成一行 `素材id:角色`(这一格本来就是行的列表,每行 `素材:角色`)。

### 2. 默认角色是「参考图」,而且**必须看得见、改得动**

默认 `reference_image`,理由:

- 「我在提示词里点了一下这张图」最普遍的意思就是**让它看着这张图**(风格、主体),不是让它当第一格画面;
- 首帧会**改变这次生成是什么**(图生视频),而默认值该表达"照它来",不该替用户决定"从它开始";
- 这一格可以是图 / 视频 / 音频三种生成,而"没写角色"的兜底本来是按 kind 分的
  (`DEFAULT_ROLE_BY_KIND`)—— 但那是**解析器的兜底**,这里是替用户**加一行**,更该保守;
  模型只收首帧时(见下)宁可**不并**并让用户自己点一下,也不猜一个会改变结果的角色。

角色不同结果不同,**所以默认值必须在界面上看得见**:检查器里那一行按角色摆出选择器,
能换成这个模型收得下的任何一种(`source_assets_roles` 记用户改过的,一条一个 `引用路径:角色`);
× 写进 `source_assets_excluded`(一条一个引用路径,下一轮不再塞回来),↺ 取回。

### 3. 能力闸:模型不收这个角色就不并 —— 但也不沉默

**判据是既有的那一套**:`generation.operations.takes_source_role` 看描述符
(`parameter_keys` 里的角色,和生成漏斗、模型选择器同一处);有连接身份时走逐模型解析
(用户在自己那行模型上声明的能力档案也生效),没有就退回内置目录。

三条刻意选择:

1. **认不出这个模型 = 不收。** 和 `validate_against_capabilities` 那边「认不出就放行」刚好相反:
   那边放行是让服务商自己判;这边是**替用户往请求里加东西**,说不清它收就不加。界面用的是同一份
   描述符,所以两边说的是同一句话。
2. **不收时界面上明说**「这个模型不接受参考图,引用的图不会被送进去」,并把模型收得下的角色列出来
   (换成首帧就能发)。沉默地丢掉和硬塞都不许。
3. **不是这个角色要的那类素材,跳过**(`SOURCE_ROLE_MEDIA`:并成 `reference_image` 的必须是图片)。
   一段视频当参考图发出去,换来的是提交期的 400 —— 而用户的提示词没有任何问题。

### 4. 手动那三条语义和大模型节点那一笔逐字相同

手动挑的保留且排在前;手动删掉的(×)下一轮不再塞回来;不是素材的引用(文字、非该角色的素材)
跳过不报错。区别只在**这一格多了一个"角色"维度**:用户的角色选择也记成一份账,同样删得掉、
点得回来。

## Consequences

- 老图**不用改 config**(和大模型节点那一笔同一条);
- 界面与运行时读**同一份声明**(`ref_assets_from` / `ref_assets_role`),前端不另抄表
  (`workflows/referencedImages.ts` + 检查器那一行);
- 生成节点上「并进来的那份以什么角色发」现在**看得见**了 —— 此前这件事只存在于用户的记忆里;
- 已知边界(和大模型节点那一笔**同一个**):**整条提示词就是一个引用**(`{{图.asset_id}}`)时,
  规范化把它升级成一条数据边,config 原文里不再有那处引用 —— 两边都看不见它。
  要覆盖它得让推导同时认数据边(引擎、绑定、前端三处),留给单独一笔;
- 上限 / 互斥那几条既有规矩不受影响:并进来的行照旧过 `keep_source_group` 和描述符的
  `source_limits`(互斥组里那一条会被丢掉 —— 那是用户明说的"这次只发首尾帧")。

## 实现记录

- 后端:`node_types.py`(`ref_assets_from` / `ref_assets_role` / `ref_assets_gate` +
  `source_assets_excluded` / `source_assets_roles`)、`binding.with_referenced_assets`(角色与闸)、
  `generation.operations.takes_source_role`、`descriptors/shared.py` 的 `SOURCE_ROLE_MEDIA`;
- 前端:`nodeInspectorGenerate` 的自动那一行(角色选择、× / ↺)、`lib/sourceFrames.roleMedia`;
- 钉住:`backend/tests/test_ai_generate_sees_referenced_images.py`(工作流真跑一遍,断言这一次交给
  模型的素材与角色)、`frontend/src/features/workflows/NodeInspector.autoSources.dom.test.tsx`、
  `referencedImages.test.ts`。
