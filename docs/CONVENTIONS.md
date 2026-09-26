# 约定与结构性约束

这份文档记两件事:**写代码时照着做的约定**,和**仓库自己会检查的约束**。

区别很重要。约定靠人记,读到了就照做;约束不靠人记 —— 违反了测试会红。所以下面第二部分的
每一条都对应一个真实的测试文件,而不是一句期望。

---

## 前端约定

### 样式

- 交互控件一律用 JSX 上的 Tailwind 类加本地的 shadcn/ui 组件。不写全局类,也不搞共享的
  class 字符串文件 —— 那两样都会变成第二个样式系统。
- 字号走 `text-ui-*` token(有哪几档由 `design/tokens.css` 说了算),不写死像素。写死的 `text-[11px]` 不跟屏幕走,而且各写各的;
  这一条有棘轮守着(`lib/typeScale.test.ts`),特例列在它的 `ALLOWED` 里。
- 圆角走 8px 刻度,分段控件是胶囊形,表单填充用 `--field`。不用投影。
- 按钮高度走 `Button` 的 `size` 档,不在 className 里改高宽。四档:`xs`/`icon-xs` 28px(工具栏)、
  `sm`/`icon-sm` 32px、`default`/`icon` 36px、`lg` 40px。缺一档就往 `buttonVariants` 里加一档 ——
  就地写 `h-7 w-7` 盖住 `size="icon"` 的代价是漏一处就露 8px,智能体输入框栽过这一下。
  棘轮:`components/ui/buttonScale.test.ts`,一次性尺寸列在它的 `GRANDFATHERED` 里。
- 设置页只保留页面主面板这一层容器。section 使用 `components/settings/settings-layout.tsx` 的平面
  `SettingsGroup`(设置、插件、定时任务、管理四页共用),相邻 section 之间那条线由
  `SettingsSectionStack` 用**相邻兄弟选择器**画在后一节身上 —— 不插独立元素:此前是「index > 0
  就插一条」,于是一个只走 portal 的孩子(AlertDialog)就能让页面末尾多出一条底下什么都没有的线。
  同类数据行使用 `SettingsList` 的分割线,不要给每个 section、每一行再套圆角边框和背景。输入控件、可选择卡片、
  独立状态面板等确实需要交互或语义边界的元素可以保留边框。
- **停靠的栏之间只有一条 1px 分割线,没有缝。** 可拖宽的栏用 `lib/useResizableSidebar`
  (`useResizableSidebar` / `useSidePanels` / `HANDLE_COLUMN` + `handleOffset`),拖柄压在那条线的
  正中;grid 上不要再加 `gap-*`,否则拖柄会悬在离线几像素的空白里、和别的页一处有缝一处没缝。
  只有画布上的浮动卡片(`RightDockResizeHandle`、工作流右侧上下两块)之间真有缝,那里显式传
  `handleOffset(size, { gap: 8 })`。棘轮:`lib/dragHandle.test.ts`。
- **新页面挂进 `app/pages.tsx` 时用 `React.lazy`。** 静态 import 会把那一页连同它的依赖
  (图编辑器、富文本内核、图表、three.js)拖回主包,而打包照样成功、测试照样全绿 —— 十四个页面
  这么攒出过一个 4.20 MB 的主包(现在 0.28 MB)。兜底的 Suspense 在 App 的渲染出口上,页面不必
  各写一次。首屏那一页(home)例外。棘轮:`app/pageChunks.test.ts`。
- 每个新界面都要同时管好浅色和深色。
- **功能模块之间不得互相依赖。** 一处功能引用另一处没问题(画板放一张 3D 场景卡),两边互相
  引用永远说明有个东西站错了地方:通用工具放 `lib/` 或 `components/`,属于某个领域的东西放回
  它的领域(评论归协作、录制归素材)。棘轮:`features/featureBoundaries.test.ts`。
- **控件的字号字重直接写在控件上就行。** `design/tokens.css` 里那条
  `button, input, select, textarea { font: inherit }` 曾经是无层级的,压过 `@layer utilities`,
  于是写在按钮上的 `text-ui-xs` 会静默失效(class 还在,尺寸回落到继承值);2026-08 那一轮
  把它挪进了 `@layer base`,并把 `ui/` 下的组件按本项目的 ui-* 刻度重定了一遍。
  没写字体类的控件仍然继承。棘轮:`design/unlayeredGlobals.test.ts`。
- **第三方组件的样式表在 `design/tokens.css` 里以 `@import … layer(vendor)` 引入,不在 JS 里
  import。** JS 里 import 的 CSS 不分层,压过所有工具类:工作流里真/假分支的红绿、数据线的
  主色和线宽写了几个月,一条都没生效。层序 `theme, base, vendor, components, utilities` 在
  tokens.css 第一句说定。给它们上色先找组件公开的 CSS 变量(React Flow 的 `--xy-*`),
  变量够不着的才用 `[&_.x]:` 任意选择器 —— 而选择器里的 `__` 必须写成 `\_\_`(整串 String.raw),
  否则 Tailwind 把 `_` 换成空格、规则选不中任何东西。
  棘轮:`design/vendorStyles.test.ts`、`design/arbitrarySelectors.test.ts`。
- **画布连线只有一套外观,在 `components/app/canvasEdges.ts`。** 工作流(含循环体/子图那一层)和
  创意画板共用:容器挂 `CANVAS_EDGE_CLASS`,每条边带 `CANVAS_EDGE_OPTIONS`(箭头、命中宽度),
  有语义的边挂 `canvasEdgeClass(tone, { flow })` 给的类。别处不写线色、线宽、箭头、虚线、
  `connectionLineStyle`。意思不同才长得不同:

  | 变体 | 意思 | 样子 |
  |---|---|---|
  | 引用 / 控制流(默认) | 画板的上游 → 下游;工作流的执行顺序 | `--canvas-edge` 实线 2px + 闭合箭头 |
  | `true` / `false` | 条件节点的真 / 假两路 | `--success` / `--destructive` 实线 + 箭头 + 标签 |
  | `data` + flow | 端口之间传值 | `--primary` 流动虚线,无箭头 |
  | `mismatch` + flow | 数据线两端类型不兼容(软提示) | `--warning` 流动虚线,无箭头 |
  | `taken`(数据线再带 flow) | 上一次运行走过 | `--canvas-edge-run`(紫,不和「真」那一路的绿撞),选中那一档线宽 |
  | `pending` / 拖线途中 | 松手在空白处待选 / 正在拉 | `--primary` 静止虚线 + 箭头 |
  | 悬停 / 选中 | —— | 本色往前景色走一截、2.5px / `--primary`、2.75px |

  箭头颜色是 `context-stroke`(跟着线本身的颜色走),尺寸按画布坐标定(不随线宽胀缩)。
  画板上连线的层次夹在分组框和项之间(`LAYERS.edge`)。点阵和线色两个令牌
  (`--canvas-dot`、`--canvas-edge`)一起调,对比度有测试盯着。
  棘轮:`components/app/canvasEdges.test.ts`。

### 布局

- 纵向堆叠用 grid/flex 加 `gap`,不用 `space-y`。Tailwind v4 把它实现成前一个子元素的
  `margin-bottom`,对 label 这类行内子元素是空操作。`components/ui/` 里几个 vendored 的
  shadcn 组件还留着 `space-y`,那是上游原样,它们的子元素都是块级,不受这条影响。
- 用内联 style 定位的元素,不要同时挂 Tailwind 的 translate/inset 类 —— v4 的独立
  `translate` 属性会和内联 `transform` 叠加。
- 单列 grid 想让内容可收缩,轨道要写成 `grid-cols-[minmax(0,1fr)]`。默认的隐式列是
  `auto` 也就是 max-content,长内容会把宽度顶开,而给子元素加 `min-w-0` **约束不到轨道**。
- 负外边距(`-mx-N`)抵消外壳内边距时,两者是一对。改外壳内边距而不动它,页面就会横向溢出。
- 业务弹窗统一用 `components/app/modals.tsx` 的 `ModalShell`:外壳 `overflow-hidden`,标题与动作区
  分别 sticky 在顶/底,只有中间 body 纵向滚动。头尾使用与中段同源的半透明 `popover` 表面加
  backdrop blur,不能另铺一块完全不透明的异色底。body 必须保留上下内边距,不能让第一个/最后一个
  控件贴住 overflow 裁剪线 —— `focus-visible` 的 ring 画在控件边框外,贴边时会被切掉。命令面板与
  纯媒体预览有自己的交互模型,可直接使用底层 `DialogContent`,但表面仍须采用 `popover/90` +
  backdrop blur,不能退回完全不透明的遮挡块；普通表单不能绕过公共壳。

### 数据与交互

- 服务端实体留在 React Query 里;Zustand 只放草稿和瞬时 UI 状态。
- **缓存键的失效用最短前缀。** React Query 按前缀匹配,所以同一份数据用几种形状的键并存时,
  刷不刷得到全看谁比谁长:剪辑页按 `["assets", 工作区, 项目]` 失效,首页按 `["assets", 工作区]`
  取数 —— 三段匹配不到两段,导入的素材在首页不出现。素材这一族已收进 `api/queryKeys.ts`
  (`list()` 取数、`all()` 失效),棘轮 `api/queryKeys.test.ts`。别的键族还是内联字面量,
  新写的尽量跟着这个形状走。
- 不用 `alert` / `confirm` / `prompt` 这些原生弹窗。
- 所有用户可见文案走 i18n(`src/app/messages.ts`),中英两份都要有。
- 时间线的几何计算住在 `domain/timeline/geometry.ts`,是有测试的纯函数;组件里不内联几何。
- 动态长列表的下拉用共享的可搜索 Combobox;拖拽交互用 dnd-kit。
- 会发请求的按钮必须显示 `loading`,而不只是 `disabled`(棘轮:`app/buttonPending.test.ts`)。
- 参考音频录制统一使用 `features/voice/useReferenceAudioRecorder.ts`，设置页与剪辑页的音色创建统一
  使用 `features/voice/VoiceCreationDialogs.tsx`。不要在页面组件里另写 `getUserMedia` / `MediaRecorder`；
  弹窗取消、切换入口和卸载都必须停止轨道，权限拒绝、录音器故障和空录音必须是不同错误。
- 领域资源跟随能力显示：工作区音色库只属于本地克隆引擎；远程 TTS 选择后只显示该供应商的音色目录，
  不保留本地音色卡片、空状态或创建入口。
- 供应商表单按真实归属命名：连接字段使用供应商/协议级 Endpoint 名称；`default_model` 兼容存储只在
  新建时显示为“初始模型”，编辑时一律去模型列表，不得重新称作供应商默认模型。

## 后端约定

### 多语言

- **领域里存 key,出口才翻。** 数据目录(发布平台、TTS 引擎、工作流节点)里写的是消息键,
  句子在接口那一层按语言组装 —— 语言从 `Accept-Language` 来,不从某个全局配置来:这是个
  多租户、可远程部署的后端,没有「服务端语言」这回事。表在 `app/core/i18n.py`,
  出口用 `t()` / `translate_fields()`。
- 两条棘轮跟着每一份目录:「目录里不许出现文案」和「写的 key 必须翻得出来」。
- **选项的值不是文案。** 下拉选项的 value 会原样存进数据、也会原样显示,没有出口能翻它 ——
  所以一律写中性标识符(`true` / `GET` / `image`),要显示什么由出口那一层决定。
- **插件清单是唯一的例外**:它是第三方写的,没法往我们的表里加词条。那里的约定是
  「一段文字既可以是字符串,也可以是 `{"zh": …, "en": …}`」,见
  [PLUGIN_MANIFEST.md](PLUGIN_MANIFEST.md#多语言)。

---

## 结构性约束(棘轮)

**棘轮**指的是只能往一个方向走的检查:存量问题冻结在一份允许清单里,新增会红,修好一处就得
把清单一起改小。它们的共同点是 —— 每一条防的漂移,都**已经真实发生过一次,而且是静默的**。

新增一条:给测试模块加上 `RATCHET = True`(Python)或 `export const RATCHET = true;`
(TypeScript),再跑一次生成脚本,它就会出现在下面。

```bash
python3 scripts/sync-ratchet-docs.py
```

<!-- BEGIN RATCHETS (generated by scripts/sync-ratchet-docs.py — do not edit by hand) -->

共 146 道。清单由脚本生成 —— 给测试加上 `RATCHET` 标记它就会出现在这里。

| 守住什么 | 测试 |
| --- | --- |
| 结构性约束:**适配器读的每个参数键,描述符都得声明。** | `backend/tests/test_adapters_read_only_declared_parameters.py` |
| 结构性约束:**「普通 / 高级」这条分界怎么划都行,但有几种划法一定是错的。** | `backend/tests/test_advanced_split_is_sane.py` |
| 智能体要能做**这个应用能做的事** —— 插件、工作流、剪辑,一样都不少。 | `backend/tests/test_agent_covers_everything.py` |
| 智能体的权限恒等式(ADR 0008 D6) | `backend/tests/test_agent_identity_ratchet.py` |
| 结构性约束:**技能清单里报出去的每条路径,都得真的存在。** | `backend/tests/test_agent_manifest_paths_exist.py` |
| 工作流有的能力,智能体也要有。 | `backend/tests/test_agent_workflow_parity.py` |
| 结构性约束:**`ai/` 是基础设施,不许认识业务**。 | `backend/tests/test_ai_is_infrastructure.py` |
| 棘轮:**接口 out schema 里的每个字段,都要有人读。** | `backend/tests/test_api_fields_reach_the_screen.py` |
| 棘轮:**请求体里的数必须是有限的**,而这条要在进门那一层挡。 | `backend/tests/test_api_refuses_non_finite_numbers.py` |
| 异步任务的轮询:六家共用的那一段。 | `backend/tests/test_async_task_polling.py` |
| 三类撤不回来的操作,同一种判据:默认问你,想让判断者接管就显式打开。 | `backend/tests/test_autopilot_has_no_allowlists.py` |
| 后端自己的多语言。 | `backend/tests/test_backend_i18n.py` |
| 空密钥不发 `Authorization` —— 而且这条规矩**只有一处实现**。 | `backend/tests/test_bearer_header_is_built_in_one_place.py` |
| 每一处 `billable(...)` 都要**说出**自己的幂等键,没有隐式兜底。 | `backend/tests/test_billing_keys_are_deliberate.py` |
| 智能体改画板走的是**细粒度算子**,不是重写整份画布。 | `backend/tests/test_board_ops.py` |
| 描述符要和供应商的真实接口对得上。 | `backend/tests/test_capabilities_match_reality.py` |
| 选择卡**只在它自己那次对话里出现**。 | `backend/tests/test_card_session_isolation.py` |
| 读目录里那几格文案的地方,**要么翻,要么明说自己在传 key**。 | `backend/tests/test_catalog_labels_are_translated_where_read.py` |
| 结构性约束:**对话补全只有一个实现**。 | `backend/tests/test_chat_single_implementation.py` |
| 棘轮:一个会改东西的工具,只在一处声明。 | `backend/tests/test_confirmable_tools_are_declared_once.py` |
| 确认卡上那句话按**读的人**的语言翻,和任务消息同一条规矩。 | `backend/tests/test_confirmation_cards_speak_the_readers_language.py` |
| 一句「另一侧还有一份,必须跟我一致」,必须**点名它归哪个契约**。 | `backend/tests/test_cross_runtime_claims_name_a_contract.py` |
| 数据归属棘轮:表的行创建只能发生在拥有它的领域模块里(ownership.py)。 | `backend/tests/test_data_ownership_ratchet.py` |
| 结构性约束:**供应商声明的每一样能力,都得真有东西去执行它。** | `backend/tests/test_declared_capabilities_have_an_implementation.py` |
| 结构性约束:**子字段的值不能比它依赖的父字段活得久。** | `backend/tests/test_dependent_fields_are_declared.py` |
| 棘轮:**桌面端运行时要加载的东西,开发态必须先构建好、并且跟着改动重建。** | `backend/tests/test_dev_mode_builds_what_the_app_loads.py` |
| 棘轮:**文档里指到的代码路径必须真的存在**。 | `backend/tests/test_docs_do_not_point_at_ghosts.py` |
| 切片是实现细节,装配入口是公共 Interface。 | `backend/tests/test_domain_assembly_entries.py` |
| 结构性约束:**领域层不认识 HTTP。** | `backend/tests/test_domain_does_not_raise_http.py` |
| 棘轮:**指向某样东西的节点字段给选择器,不给文本框。** | `backend/tests/test_entity_fields_have_a_picker.py` |
| 每一处 `chat()` 调用都要记账 —— **不能靠调用方记得传 `call=`**。 | `backend/tests/test_every_chat_call_is_billed.py` |
| 棘轮:**每一张会落「进行中」的表,都要说得出重启之后谁来收尾。** | `backend/tests/test_every_in_flight_row_has_someone_to_settle_it.py` |
| 棘轮:**每个节点类型在画布上都有自己的图标**。 | `backend/tests/test_every_node_type_has_an_icon.py` |
| 执行器**真正返回**的键,必须在节点注册表里声明过。 | `backend/tests/test_executor_outputs_are_declared.py` |
| 节点执行器只从运行作用域里读 workspace_id / id / name 三样。 | `backend/tests/test_executors_only_read_run_scope.py` |
| 字段用哪种专用控件,由**字段声明**点名(`editor`),不由界面按「节点类型 + 字段名」认。 | `backend/tests/test_field_editors_are_declared.py` |
| 结构性约束:**字段说明不能只是把标签再说一遍。** | `backend/tests/test_field_help_says_something_new.py` |
| 结构性约束:**自由文本字段必须声明成 `template`。** | `backend/tests/test_free_text_fields_are_templates.py` |
| 打包版的后端**不是一个 Python 解释器**,也**没有 .py 源文件在盘上**。 | `backend/tests/test_frozen_build_is_not_a_python_interpreter.py` |
| 棘轮:**多能力供应商下,认不出、也没标过能力的模型不出现在任何生成入口里。** | `backend/tests/test_generation_capabilities_need_evidence.py` |
| 时间线上有 GIF 时,取当前帧和导出都要跑得通。 | `backend/tests/test_gif_on_timeline_renders.py` |
| 这台电脑上的文件是**部署主人的** —— 读一个用户给出的本机路径,只在一处判,每个入口都算数。 | `backend/tests/test_host_files_belong_to_the_deployment_owner.py` |
| 棘轮:**执行体写任务状态走 finish_job,不直接 `job.status = …`**。 | `backend/tests/test_job_status_goes_through_finish_job.py` |
| 建了 job 就得让总线派发它,不许自己起线程。 | `backend/tests/test_jobs_are_dispatched_by_the_bus.py` |
| 挪一个标记不是一次「执行版本」。 | `backend/tests/test_markers_do_not_make_revisions.py` |
| 冒烟测试:**每个工具发出去的载荷,后端接得住。** | `backend/tests/test_mcp_tool_payloads.py` |
| 棘轮:**跑过一次的迁移,身体不能再改。** | `backend/tests/test_migration_bodies_are_frozen.py` |
| 内置的模型上限表:形状、优先级、以及「宁可报小」那条。 | `backend/tests/test_model_limits.py` |
| 内嵌子图(循环体 / subgraph)**体内看得见什么**,由节点自己声明一次(`body_scope`)。 | `backend/tests/test_nested_body_scope_is_declared_once.py` |
| 工作流引擎同时占的连接数,必须由**池子的容量**决定,而不是三个相乘的常数。 | `backend/tests/test_nested_graphs_stay_inside_the_pool.py` |
| 棘轮:**新加的迁移,必须带一条喂它旧形状数据的测试。** | `backend/tests/test_new_migrations_come_with_a_test.py` |
| 吞掉异常不许再变多。 | `backend/tests/test_no_new_silent_swallows_on_the_clone_path.py` |
| 报错不许再按位置裁子进程的输出。 | `backend/tests/test_no_new_tail_cutting_error_messages.py` |
| 棘轮:节点**声明的输出**和执行体**真正返回的键**是同一批。 | `backend/tests/test_node_outputs_match_the_executor.py` |
| 对象存储是**一个插件、五个服务商选项**,各家的差异只住在 providers.py 那一张表里。 | `backend/tests/test_object_storage_plugin.py` |
| 棘轮:插件字段的说明里写着「可以不填」,清单里就得声明 `required: false`。 | `backend/tests/test_optional_plugin_fields_are_not_required.py` |
| 付过钱的远端生成,只有两种结束方式:远端给出终态,或者用户取消。 | `backend/tests/test_paid_generations_are_never_abandoned.py` |
| 宿主把一份**文件**交给插件。 | `backend/tests/test_plugin_inputs.py` |
| 插件清单里给人看的文字必须能跟着界面语言走。 | `backend/tests/test_plugin_manifest_i18n.py` |
| 插件节点在**每一条**校验路径上都认得出来,而不只是保存和运行那两条。 | `backend/tests/test_plugin_nodes_are_known_everywhere.py` |
| 插件节点的表单也要能分「普通 / 高级」。 | `backend/tests/test_plugin_nodes_support_advanced.py` |
| 插件的 README 要能在官网上渲染出来。 | `backend/tests/test_plugin_readme_renders.py` |
| 插件市场索引必须和插件清单对得上。 | `backend/tests/test_plugin_registry_in_sync.py` |
| 内置的官方价目表:形状、查表规则、中转的借价规则。 | `backend/tests/test_price_reference.py` |
| 私有的发布账号与浏览器池档案,**管**只认主人 —— 共享出去是借给人用,不是交给人管。 | `backend/tests/test_private_identities_are_managed_by_their_owner.py` |
| 私有的发布账号与浏览器池档案,只有主人和被共享到的人能**用** —— 在用的那一刻查,每个入口都算数。 | `backend/tests/test_private_identities_need_their_owner.py` |
| 棘轮:下划线开头的名字不跨包引用。 | `backend/tests/test_private_names_stay_in_their_package.py` |
| 结构性约束:**清过缓存之后,在飞的那次探测不算数。** | `backend/tests/test_probe_generations.py` |
| 结构性约束:**每一处模块级可变状态都在 docs/PROCESS_STATE.md 里有交代**。 | `backend/tests/test_process_state_inventory.py` |
| Provider 的能力 Interface、供应商 Adapter 和 Registry 不能重新混成一层。 | `backend/tests/test_provider_architecture.py` |
| 棘轮:**每个发布状态都要被归到首页那三档里的一档**,不多不少。 | `backend/tests/test_publish_statuses_are_all_classified.py` |
| 结构性约束:**docs/CONVENTIONS.md 的棘轮清单与代码一致**。 | `backend/tests/test_ratchet_docs_in_sync.py` |
| 撤掉的模型不留残影:代码里不再有它们的 id、档案名和 Adapter。 | `backend/tests/test_removed_models_leave_no_trace.py` |
| 一次运行用私有的东西,要**点运行的人**和**被执行那一版图的担保人**都过得了闸。 | `backend/tests/test_runs_act_with_the_revision_authors_authority.py` |
| 用户在「模型设置」里填的每一格,**两条执行通道上都要有人读它**。 | `backend/tests/test_runtime_fields_reach_both_channels.py` |
| 「这个本机引擎跑不跑得起来」只有一种回答方式:**起子进程 import 一次**。 | `backend/tests/test_runtime_readiness_is_an_import_probe.py` |
| 模型上加了列,就得有迁移把它加到**已存在的库**上。 | `backend/tests/test_schema_migrations_cover_the_models.py` |
| 密钥不该明文落盘。 | `backend/tests/test_secrets_at_rest.py` |
| 设置 API 只是统一 URL 前缀，不是一个能吞下所有设置领域的模块。 | `backend/tests/test_settings_route_boundaries.py` |
| 东西删了,它的共享记录也得跟着走。 | `backend/tests/test_sharing_forgets_on_delete.py` |
| sidecar 发得出的每一种事件,后端都要有一个分支接它。 | `backend/tests/test_sidecar_events_have_consumers.py` |
| 棘轮:**协议请求方向上声明的每个字段,sidecar 那侧都要真的读它。** | `backend/tests/test_sidecar_requests_have_readers.py` |
| 说「唯一实现 / 唯一入口 / 只有一处」的注释,要么点名守着它的检查,要么进存量名单。 | `backend/tests/test_single_point_claims_name_their_guard.py` |
| 棘轮:**官网文档两种语言要对得上,而且别把数目写死错**。 | `backend/tests/test_site_docs_stay_in_sync.py` |
| 结构性约束:**「有哪几种输入素材角色」只有一个产地。** | `backend/tests/test_source_roles_have_one_home.py` |
| `sqlite3.connect()` 不许直接当 `with` 用 —— 那个 with 管事务,不关连接。 | `backend/tests/test_sqlite_connections_are_closed.py` |
| 取当前帧走的是**渲染那条路**,不是抓预览的画布。 | `backend/tests/test_still_frame_goes_through_render.py` |
| 外部命令只从一个口子出去。 | `backend/tests/test_subprocess_has_one_door.py` |
| 文本 I/O 必须**自己说清用什么编码**,不能问平台要。 | `backend/tests/test_text_io_never_inherits_the_platform_encoding.py` |
| 知识库整块删掉了。 | `backend/tests/test_the_knowledge_base_is_gone.py` |
| 「能对时间线做什么」只有**一份**数据,而且它说的是实话。 | `backend/tests/test_timeline_ops_have_one_list.py` |
| 结构性约束:**docs/MCP.md 的工具清单与代码一致**。 | `backend/tests/test_tool_docs_in_sync.py` |
| 结构性约束:**记进操作日志的每一种操作,都要登记它的逆操作。** | `backend/tests/test_undo_registry.py` |
| 结构性约束:**记账只有一个入口**。 | `backend/tests/test_usage_single_entry.py` |
| 棘轮:后端报给人看的错误**不写死中文句子**。 | `backend/tests/test_user_facing_errors_are_translated.py` |
| 结构性约束:`ai/runtime/workers/` 下的脚本**不许 import app.***。 | `backend/tests/test_workers_run_under_another_interpreter.py` |
| 棘轮:工作流跑失败时那句话,也得跟着读的人的语言走。 | `backend/tests/test_workflow_errors_speak_your_language.py` |
| 条件字段的后端一侧：跑 contracts/workflow-field-activation.json。 | `backend/tests/test_workflow_field_activation_parity.py` |
| 棘轮:**从 config 拿实体 id 的节点,必须把它收进本工作流的工作区**。 | `backend/tests/test_workflow_nodes_stay_in_their_workspace.py` |
| 写权限是**写出来的**,不是从请求方法推出来的。 | `backend/tests/test_write_permission_is_explicit.py` |
| | |
| 素材缓存的键:取数可以细,失效必须粗。 | `frontend/src/api/queryKeys.test.ts` |
| 结构性约束:**会发请求的按钮必须反映它自己的进行中状态**。 | `frontend/src/app/buttonPending.test.ts` |
| 结构性约束:**装智能体正文的滚动容器,横向也要锁死。** | `frontend/src/app/chatScroll.test.ts` |
| **会裁切的盒子不能用 `leading-none`。** | `frontend/src/app/clippedText.test.ts` |
| `createContext` 所在的模块不许引 UI 组件。 | `frontend/src/app/contextIdentity.test.ts` |
| 自定义 CSS 能不能压过应用样式,全看**注入的那个 `<style>` 排在哪**。 | `frontend/src/app/customCss.dom.test.tsx` |
| 文案表里**不留没人用的条目**。 | `frontend/src/app/messages.unused.test.ts` |
| 页面**按需加载**,不许被直接 import 回主包。 | `frontend/src/app/pageChunks.test.ts` |
| 棘轮:**画布连线长什么样,只在 components/app/canvasEdges 一处说。** | `frontend/src/components/app/canvasEdges.test.ts` |
| 棘轮:**每块 React Flow 画布的删除键都走 useCanvasDeleteKey**。 | `frontend/src/components/app/useCanvasDeleteKey.test.ts` |
| 按钮的尺寸刻度只能来自 token,不能在调用点重定义。 | `frontend/src/components/ui/buttonScale.test.ts` |
| 棘轮:**按钮、输入框、下拉触发器的高度只有一个出处**(control-size.ts)。 | `frontend/src/components/ui/controlSize.test.ts` |
| 智能体时间线的字号**只有一个出处**。 | `frontend/src/design/agentTypeScale.test.ts` |
| 棘轮:**接口的路径只写在 `api/domains/*` 里**,而且这个数字只减不增。 | `frontend/src/design/apiSeam.test.ts` |
| Tailwind 任意选择器里的 BEM 类名,`__` 必须写成 `\_\_`。 | `frontend/src/design/arbitrarySelectors.test.ts` |
| 同一行里的控件要一样高。 | `frontend/src/design/controlRhythm.test.ts` |
| 输入框和下拉触发器的高度只能来自 `size` 档位,不能在调用点用 className 改。 | `frontend/src/design/fieldScale.test.ts` |
| 锁了行轴就得锁列轴 —— 只写 `grid-rows` 会让隐式列按 max-content 定尺。 | `frontend/src/design/gridAxes.test.ts` |
| 键帽只有一种长相:`<kbd>` 只在 components/ui/kbd.tsx 里写。 | `frontend/src/design/keycaps.test.ts` |
| 棘轮:**底下那几层不许认识功能模块**。 | `frontend/src/design/layering.test.ts` |
| 同级元素的重复间距只由父容器控制。 | `frontend/src/design/layoutRhythm.test.ts` |
| 仓库链接只能指向 **main**,而且只能指向真实存在的路径。 | `frontend/src/design/repoLinks.test.ts` |
| 选项来自服务端的下拉,要么走 OptionPicker(过阈值自动换成可搜索的那版),要么给出理由。 | `frontend/src/design/searchableLists.test.ts` |
| 加载占位一律走 components/ui/skeleton 的扫光,不再有各写各的 animate-pulse 灰块。 | `frontend/src/design/skeletons.test.ts` |
| 棘轮:界面上给人看的字**走文案表**(`app/messages.ts` 的中英两份),不在组件里写死中文。 | `frontend/src/design/uiTextIsTranslated.test.ts` |
| tokens.css 里给全局兜底的那几条规则,**必须写在 @layer 里面**。 | `frontend/src/design/unlayeredGlobals.test.ts` |
| 第三方组件的样式表**必须进主包**,而且**必须进 vendor 层**。 | `frontend/src/design/vendorStyles.test.ts` |
| 棘轮:**画布上的叠放顺序不许在调用处现挑一个数。** | `frontend/src/features/canvasLayers.test.ts` |
| 配音完成后要刷**哪些**缓存。 | `frontend/src/features/editor/dubRefresh.test.ts` |
| 剪辑台上的分段 tab 只有一种长相。 | `frontend/src/features/editor/editorTabRhythm.test.ts` |
| 画不出来时的那块提示,必须在监视器的**最上层**。 | `frontend/src/features/editor/playback/previewOverlayLayer.test.ts` |
| 字幕翻译的引擎选择必须真的传到后端。 | `frontend/src/features/editor/subtitleTranslateEngine.test.ts` |
| 转写正跑着的时候,逐字稿面板不能说「还没有转写结果」。 | `frontend/src/features/editor/transcriptBusyState.test.ts` |
| 功能模块之间**不得互相依赖**。 | `frontend/src/features/featureBoundaries.test.ts` |
| 弹层的横向必须锁死。 | `frontend/src/features/media/urlImportLayout.test.ts` |
| 设置页里的一项是**一行**,不是一张带边框的卡片。 | `frontend/src/features/settings/rowsNotCards.test.ts` |
| 设置组件自己拥有纵向节奏，调用方不能再从外面叠加一层。 | `frontend/src/features/settings/spacingContract.test.ts` |
| 棘轮:**节点检查器不认识任何具体节点**。 | `frontend/src/features/workflows/nodeInspectorIsNodeAgnostic.test.ts` |
| 官方工作流的名字和介绍**只写一处**。 | `frontend/src/features/workflows/workflowTemplateText.test.ts` |
| 拖柄长什么样,**全应用只有一份定义**。 | `frontend/src/lib/dragHandle.test.ts` |
| 参数控件由**模型的描述符**决定,不由 kind 写死。 | `frontend/src/lib/generationCapabilities.test.ts` |
| 结构性约束:**生成模型选择器不拿清单第一项当默认** —— 落在存着的那个、用户设的默认,或者什么都不选。 | `frontend/src/lib/generationPickerDefault.test.ts` |
| 「还没测过」不能显示成「跑不起来」。 | `frontend/src/lib/runtimeChecked.test.ts` |
| 界面字号走 token,不写死像素。 | `frontend/src/lib/typeScale.test.ts` |
| 无边框窗顶栏给系统按钮让位的规则,**只能有一份**。 | `frontend/src/lib/windowChrome.test.ts` |
| 自定义 CSS 的文件这一侧:文件在哪、监听盯的是什么。 | `electron/system/customCss.test.ts` |

<!-- END RATCHETS -->

---

## 契约(contracts/)

跨实现的一致性不靠注释,靠 `contracts/` 下的可执行规约:同一份语料前后端各跑一遍,两边答案
必须一样。预览与导出的画面一致性就是这么钉住的。

一句「另一侧还有一份,必须跟我一致」的注释,必须点名它归哪个契约 —— 否则这件事要不要进契约,
就取决于有没有人正好读到那句注释,而注意力不是机制(棘轮:
`backend/tests/test_cross_runtime_claims_name_a_contract.py`)。

详见 [contracts/README.md](../contracts/README.md)。
