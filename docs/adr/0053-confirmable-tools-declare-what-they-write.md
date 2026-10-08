# ADR 0053:需要确认的工具自己说改了哪些数据,界面按一张表刷新

## Status

Accepted — 2026-10-09。维护者 2026-10-09 按推荐拍板(体检编号 D54;对应前端架构分析 FA-05 长远的那一半)。实现与本篇同一次提交,
见文末「实现记录」。

## Context

智能体开的确认卡批完之后,界面上哪些列表、详情该重取,此前靠前端一份**按工具逐行手写的清单**
(`features/agent/confirmationCaches.invalidateAfterDecision`)。每张卡批完都把整份清单刷一遍,拒掉的也一样。

这份清单和后端的工具登记表(`backend/app/domain/agent/confirmable/`)之间没有任何联系:后端加一种会直接改数据的卡,前端得有人记得
来补一行。2026-10-08 的体检里它就漏了四样 —— 项目(在剪辑页里批掉「删除项目 X」,切换器还列着 X、剪辑页还开着 X,接下来的请求 404)、
发布任务、工作流的运行记录、技能。当时是照着登记表逐个核过、手补上的;下一种卡还会再漏一次。

任务那一侧早就不是这样:每种任务在后端目录里声明做完会改哪些数据(`job_catalog.JobKind.affects`,ADR 0018),前端一张
「数据种类 → 缓存键」的表把它换成缓存键。确认卡缺的就是同一套东西。

## Decision

1. **每个需要确认的工具声明 `writes`**:批准执行之后,`execute` **当场**改了哪几种数据。`ConfirmableTool.writes` 没有缺省值 ——
   新加一个工具不写它,构造就失败(导入登记表就报错,整套测试都红)。
   - 只算 `execute` 自己写的。起了后台任务的卡(生成、转换、导入、渲染、配音)不替任务说:任务做完时按它自己的 `affects` 刷新。
   - 后果在应用之外的(发 HTTP 请求、跑代码、改 Blender 或 ComfyUI 画布上的东西、开浏览器会话)写 `()`,而且必须明写。
   - 插件工具一族写 `("assets",)`:插件交出的文件收进这个工作区的素材库。
2. **一套词,任务和工具共用**:`backend/app/domain/resources.py` 的 `Resource`。在任务原来那 9 个词之外加了 `projects`、`notes`、`skills`。
   `JobKindOut.affects` 和卡上的 `writes` 都按这个 `Literal` 生成 OpenAPI 枚举,前端的类型从它来。
3. **卡的接口带着它**:`ConfirmationOut.writes` 按登记表现算。认不出的工具(老卡、插件被卸掉)是空的。
4. **前端只有一张「数据种类 → 缓存键」表**:`frontend/src/api/resourceKeys.ts`。任务中心和确认卡都经它把词换成缓存键(键的第一段,
   按前缀失效)。批完一张卡:
   - 卡本身每次都刷;
   - 执行完、执行失败(可能做了一半)的卡按它的 `writes` 刷;
   - 拒掉、作废的卡只刷卡。
   - 不是这个界面批的卡(自动放行、飞书、另一台设备)落地之后,按新落地的那几张各自的 `writes` 刷。
   手写清单删掉。
5. **两道棘轮**:
   - `backend/tests/test_confirmable_tools_declare_writes.py`:每个开卡工具都在登记表里、都声明了、用的都是词表里的词、和任务目录
     同一套词;卡的接口带着它。
   - `frontend/src/api/resourceKeys.test.ts`:后端的每一个词这张表里都有、而且给了键;表里写的每个键都真有查询在用。前端的类型检查
     另外守着「表里不多不少」(`Record<Resource, …>`)。

## Consequences

- 加一种会改数据的卡,声明写在工具旁边;忘了写就红。加一种新数据,后端加一个词、前端那张表加一行键;漏了任何一边都红。
- 拒掉的卡不再把整份清单刷一遍。
- 有几张卡比手写清单刷得更准:
  - 插件工具、`run_plugin_tool` 批完,素材库当场出现插件交出的文件。此前清单里写着「改了什么说不准,不猜」。
  - 生成类的卡多刷了创作会话。
  - 只起后台任务的卡不再白刷素材、时间线。
- **声明是工具作者说的**,测试只管「写了、写的是认得的词、有键」,管不到「说的是实话」。`execute` 当场多写了一样却没声明,界面就不刷那一样;
  这和任务的 `affects` 是同一种信任。在 `writes` 的说明里写明了只算当场写的、后果在外面的写 `()`,评审时对着 `execute` 看。

## 实现记录(2026-10-09)

- 后端:
  - 新增 `app/domain/resources.py`,`job_catalog.Resource` 改为从这里来;
  - `ConfirmableTool.writes`(在 `registry.py` 的 `__post_init__` 里校验),38 个逐个登记的工具和插件工具一族各自声明;
  - `ConfirmationOut.writes`;`JobKindOut.affects` 收紧成同一个枚举。`openapi.json` 和 `schema.d.ts` 重新生成。
- 前端:
  - 新增 `api/resourceKeys.ts`(表、`queryKeysFor`、`invalidateResources`);`components/jobs/jobKinds` 去掉自己那份表,改用它;
  - `features/agent/confirmationCaches.invalidateAfterDecision(qc, workspaceId, cards)` 按卡的 `writes` 刷新;
  - 确认中心、对话里的卡把批准 / 拒绝接口的回包传进去;落地轮询按新落地的那几张刷新。
- 声明一览:

  | 写什么 | 工具 |
  | --- | --- |
  | `workflows` | `create_workflow`、`update_workflow`、`edit_workflow`、`run_workflow` |
  | `boards` | `edit_board`、`run_board_item` |
  | `assets` + `sequences` | `delete_assets` |
  | `projects` + `assets` + `sequences` | `delete_projects` |
  | `publish_tasks` | `publish_asset` |
  | `generations` | 五个 `generate_*` |
  | `notes` | `edit_note` |
  | `sequences` | `edit_timeline` |
  | `assets` | `split_image_grid`、`reparse_document`、`run_plugin_tool`、插件工具一族 |
  | `skills` | 技能那六张 |
  | `()` | `render_sequence`、`dub_subtitles`、`separate_audio`、`denoise_audio`、`import_from_url`、`convert_video_to_gif`、`http_request`、`run_code`、`run_host_code`、`blender_execute`、`comfy_canvas_edit`、`browser_open`、`browser_pool_open` |
