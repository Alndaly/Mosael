# 官方工作流与插件:只读审计

> 日期:2026-09-30 · 基准提交:`4ed2c91d`(1.8.0 之后)
> 输入:同日三路只读审计 —— 官方工作流模板(11 个)、示例插件(6 个)、随包插件(3 个)与插件宿主。
> 「已确认」= 在代码里追到了(部分实测);「推断」= 需要运行环境才能坐实。
> 标 ✔ 的几条是写这份综合时我又自己复核过的。

---

## 0. 结论

1. **插件的安全边界比界面暗示的弱。** 清单里的 `permissions` 只是一道「用户同意」开关,运行时不做任何限制 ——
   插件进程和后端同一个系统用户,能读写这个用户碰得到的一切。这本身写在文档里(`runtime.py:17-26`、
   `PLUGIN_MANIFEST.md`),问题是**界面把它显示得像有范围**(「访问网络:comfyui」),而且有两处连「同意」这道
   开关都绕过去了(§2 H1、H2)。
2. **有三条会把凭据或签名链接送进用户可见的错误文字**,其中百度网盘的 access_token 是确定的(§2 H3)。
3. **官方工作流的结构是对的,产出不对。** 11 张图全部通过静态校验(配置键、选项值、循环字段、schema 路径),
   但有 4 个模板**跑得通、出的东西是错的**:混剪每段时长、带货短片的口播与字幕、每拍画面时长、上身图视频必失败
   (§3 H1–H4)。现有 86 个模板测试全是结构断言,没有一个模板在假供应商下完整跑通过,所以这一类一条都拦不住。
4. **时间预算三处打架**:智能体一次最多等 180 秒,几个会被就地调用的工具声明了 300–600 秒;长任务占着全局只有
   4 个的插件名额;若干渲染选项(4K、60fps × 120 秒)在自己的预算里几乎必然超时(§2 M1、§4)。

---

## 1. 地图

### 1.1 插件从包到结果

```
安装(市场/zip,部署管理员)→ 校验 https / sha256 / 路径穿越 / 解压炸弹 → 原子换目录
随包:每次启动按内容指纹整目录替换 → 登记 → 给已有连接补新工具开关
扫描:迁移清单(原地改写,留 .bak)→ 解析校验 → 写 PluginPackage
连接:归属个人、默认停用;配置明文、凭据加密;权限授予默认 false;出站网络设置
  闸门 blocked_reason = 已启用 ∧ 配置齐 ∧ 凭据齐 ∧ 权限全授予
暴露:已勾选、非内部、未被挡的工具 → 智能体 / 工作流节点 / 画板;provides → 能力选择(用户默认 > 自动挑)
调用:tools.invoke 唯一入口(外层 use_cases 查归属与 edit;智能体按 effects 决定开不开确认卡)
  → 写 running 记录 → 素材物化到临时目录 → 子进程(最小环境 + 本连接配置/凭据 + 代理变量)
  → stdout ≤ 1MB;超时/取消:取消文件 → 30s 宽限 → 杀进程树 → 产出只认临时目录内或 http(s) → 进素材库
```

信任边界只有两处:**安装时**管理员看过权限列表;**调用时**只做环境变量隔离。

### 1.2 插件一览

| 插件 | 形态 | 工具 | 依赖与锁版本 | 测试 |
|---|---|---|---|---|
| ComfyUI(随包) | 进程 | 8 个固定 + 每张工作流一个 `wf_*`(paid,默认开) | 无 | ~10 个文件 + 假服务器,好 |
| MinerU(随包) | 进程 | `mineru_parse`(上传到 mineru.net) | 无 | 9 条,都 mock |
| 对象存储(随包) | 进程 | 上传 / 签名 / 取回 / 列举 | 无 | ~30 条 + 三家 SDK 签名比对 |
| text-toolkit | 进程 | 7 个,全只读 | 标准库 | 好 |
| 百度网盘 | 进程 | 4 个 | 标准库,OAuth 自动续 | 611 行,很全 |
| TikHub | MCP http | 服务端拉,默认 paid | 零代码 | 只有静态测试 |
| Blender | MCP stdio(uvx) | 默认勾 2 个只读 | `mcp-for-blender==2.0.3` | 宿主互通有测试 |
| Remotion | 进程,流式 | 3 个 | package.json 精确版本,**无 lockfile** | 344 行 |
| Manim | 进程,流式 | 4 个 | **只锁顶层** `manim==0.21.0` | 657 行 |

### 1.3 官方工作流一览

| 模板 | 输入 → 产出 | 付费调用 / 次 |
|---|---|---|
| 整片生成 | 主题 → 成片 | 最贵:视频 × 镜数、图 7 + 镜数 × 1~2、语音 × 镜数(默认约 6 镜,schema 上限 24) |
| 口播精剪 | 口播视频 → 精剪版 | 1 次 LLM(随时长增长) |
| 译配 / 译配改口型 | 视频 → 译文字幕 + 配音(+ 口型) | N 句 × (翻译 + 语音)(+ 每块一次口型) |
| 长视频切片 | 长视频 → 多条竖屏 | 1 次 LLM |
| 商品上身 | 商品图 → 上身图(+ 视频) | 组数 × (图 + 视频),**组数无上限** |
| 带货短片 / 带货主播 | 商品 → 带货竖屏 | 拍数 × 图 + 语音(主播版 + 2 段出镜) |
| 素材混剪 | 带标签素材 → 混剪 | 1 次 LLM + ≤ 24 次语音 |
| 面料效果 | 面料图 → 效果图与规格页 | 种数 × 图,**无上限** |
| 数字人口播 | 正脸 + 稿子 → 口播 | 句数 × 语音 + 段数 × 说话视频 |

---

## 2. 插件与宿主:问题

| # | 级别 | 证据 | 问题 |
|---|---|---|---|
| H1 | 高 · 已确认 | `plugin_manifest.py:560`、`instances.py:362-370`、前端 `pluginPermissions.ts:15-19` | **权限不被执行,界面却像有范围。** 声明 `network:x` 的第三方插件照样能读 `~/.ssh`、访问任何地址。 |
| H2 | 高 · 已确认 ✔ | `tools.py:171-177`(`refresh_tools` 只查配置与凭据)、`instances.py:128/197/215` | **MCP 插件在权限授予前就被执行。** 启用连接、改凭据都会顺手拉工具清单,`npx`/`uvx` 子进程在授权前就起来了。 |
| H3 | 高 · 已确认 ✔ | `artifacts.py:116-117` `detail=str(exc)`;`baidu-pan/tools/main.py:285` 令牌拼在 URL | **凭据进错误文字。** httpx 的状态异常文字带完整 URL;dlink 过期或 403 时 access_token 落库、显示给用户、交给智能体。同一条路还会带出 `storage_fetch` 的签名串;`mcp_bridge.py:146` 可能带出展开后的 `${KEY}`;MinerU 的 SOCKS 报错会带出 `user:pass`。 |
| M1 | 中 · 已确认 | `shared-constants.json` 只约束默认 60s;`import_outputs` 600s、`DOWNLOAD_TIMEOUT_SECONDS=300`;`tools.py:332`、`:385` | **预算打架。** effects 为 none、会被智能体就地调的工具超过 180s;流式工具占全局 4 个名额,几次长上传就挡住所有插件调用(含每分钟的指纹检查);不在任务里跑的调用取消不了。 |
| M2 | 中 · 已确认(实测) | `migrations.py:215`、`packages.py:57`、`plugin_archive.py:154` | **清单类型错误会让解析器崩。** `headers` 写成列表、`args` 写成数字、`manifest_version:"x"` 抛的不是 ManifestError:一个坏目录让整次扫描失败;从文件装包返回 500。 |
| M3 | 中 · 已确认 | 同上 | **校验漏项**:`provides` 写错的能力名照收;`public_url` 多个工具认领时只取第一个;未来的 `manifest_version`、未知 `runtime.kind`、错类型的 `timeout_seconds` 都静默接受。 |
| M4 | 中 · 已确认 | `dynamic_tools._KEPT` | **运行时报出的工具绕过安装审阅**:可自报 effects=none、read_only、recommended、1800s 预算,默认开放、不开确认卡。 |
| M5 | 中 · 已确认 | 对象存储 `storage_presign` | **标成只读,却能给桶里任意对象签 7 天公网直链**:不开确认卡,被提示注入时就是一条外泄通道。 |
| M6 | 中 · 已确认 | `capabilities/__init__.py:244, 323-327` | **默认提供方停用后静默换一家**:素材被传到另一个桶或另一家服务商,不问用户,无测试。 |
| M7 | 中 · 已确认(实测) | `manim/tools/manim_guard.py` | **Manim 代码护栏可绕过**:只查 `from X import` 的模块名不查导入的名字;`from numpy import fromfile`、`np.ctypeslib.load_library`、`from networkx import read_gml` 等都能过。 |
| M8 | 中 · 已确认 | `artifacts._download` | **宿主下载产出不报进度、不能取消**:`pan_import` 下几个 GB 看不到进度也停不下来;而文档说「进度、取消全都是现成的」。 |
| M9 | 中 · 已确认 | remotion / manim 清单 | **setup 工具标 `effects: none`**,实际下几百 MB 包和 Chrome、跑安装脚本:智能体调用不弹确认。 |
| M10 | 中 · 已确认 | blender 清单;`mcp_bridge._sync` 60s | **Blender 没声明 `package_sources`**,PyPI 镜像注入不到;uvx 冷启动装 Python + 依赖,60s 内拉工具清单大概率超时(推断)。 |
| M11 | 中 · 已确认 | `remotion/tools/main.py:167`、`manim_env.py:417` | **依赖锁不全**:remotion 无 lockfile、跑 postinstall;manim 间接依赖漂移。 |
| M12 | 中 · 推断 | remotion `seconds≤120, fps=60` 对 `RENDER_TIMEOUT=150`;manim `4k` 同样 150s | **可选值在自己的预算里几乎必然超时**。manim setup 子步骤总和最坏超过声明的 1200s,被宿主掐掉而不是自己先说人话。 |
| M13 | 中 · 推断 | `child_process.py:68` `start_new_session=True`;`main.py` lifespan | **后端退出后插件进程变孤儿**;重启时记录判失败,真实进程可能还在上传。 |
| M14 | 中 · 已确认 | PATCH 连接 → notify 同步刷新 | **保存 ComfyUI 连接可能卡两分钟**(服务没开时,目录 60s + 工具 60s,都要起子进程)。 |
| L | 低 | — | 调用记录无分页、无保留期、输入不截断;前端直接显示英文状态值;MinerU 结果 zip 整份进内存且解压无总上限;ComfyUI 写死 `ProxyHandler({})`,连接的网络设置对它无效;离线时每连接每分钟仍起 2 个进程;MCP 返回不受 1MB 限制;迁移链非原子写、`.bak` 只写一次、顶层凭据可能被丢;Blender / Remotion 实际外连未写进 permissions;TikHub README 教人加 `read_only: true`;remotion 的 local-code 工具默认开放而 manim 的不开;`plugin_kit` / locale 挑选 / 进度函数各抄了 3 份;text-toolkit 没有 README;TikHub `recommended:[]`,连上后一个工具都没开。 |

---

## 3. 官方工作流:问题

11 张图的**结构**全部正确(静态校验:配置键、选项值、`loop.item` 字段、schema 路径)。问题都在**产出**。

| # | 级别 | 证据 | 问题 |
|---|---|---|---|
| H1 | 高 · 已确认 ✔ | `templates_business.py:1567-1568` 只写 `start` 与 `max_duration`;`subjobs.py:480` 缺 `end` 时取整段;`_fit_speed` 只加速且 ≤1.5× | **素材混剪每段时长错。** 60s 素材计划用 5s,实际铺进约 37s 快放画面,旁白字幕全错位。 |
| H2 | 高 · 已确认 | `templates_business.py:769` | **带货短片的口播是坏的**:只念开场钩子 + 收尾号召、放在第 0 秒,中间每拍的 narration 没人念;两版都没有字幕节点,卡片却写「配上口播与屏幕短句」。 |
| H3 | 高 · 已确认 | `sequences/append.py:18` `STILL_SECONDS=5`;`:752` | **每拍画面时长和脚本对不上**:图片上时间线固定 5s,`max_duration` 只能压到 3.33–5s;主播版画外音因此串到下一拍。 |
| H4 | 高 · 已确认 | `templates_business.py:427, 430-431`;`descriptors/video.py:266, 379`;`operations.py:1023` | **商品上身的视频一步在 Seedance 2.0 / MiniMax 上必然失败**:同时传首帧与参考图、没写 `source_group`,两组互斥 → `genErr_exclusiveSources`,且在每组图**已付费之后**才报;卡片里举的例子恰好是 Seedance 2.0。时长写死 5s,没用 `_video_plan`。 |
| M1 | 中 · 已确认 | `templates_full_video.py:68` vs `:77` | 白模提示词自相矛盾:「不要用固定的 40 米」与「position 为 [n*40,0,0]」同段;测试只禁了 `x = n*40`。 |
| M2 | 中 · 已确认 | `templates_models.py:95-104`;`translate.py:120` | **前置检查与运行时不一致**:只要 1 张参考图的三个模板套用了整片的「≥9 张」判据,能收 1–8 张的模型被判缺;译配的翻译节点运行时用第一条可用连接,不是检查时挑的对话模型(推断)。 |
| M3 | 中 · 已确认 | `:771`、`:1273` | 缺配置到运行时才发现:带货版缺音色、主播版没选主播,都要等并行的 LLM / 出图已经开始后才失败。 |
| M4 | 中 · 已确认 | `:499`、`:1637` | 默认值让第一次运行出错:整片的主题、混剪的素材标签是占位句;商品名默认空不拦。 |
| M5 | 中 · 已确认 ✔ | `MAX_VARIANTS=12` 全仓只有定义;`:334`、`:863` 无 `maxItems` | **没有费用上限**:scenes / applications 只在提示词里说数量。 |
| M6 | 中 · 已确认 | — | **英文用户拿到的仍是中文**:节点名双语,但提示词、`language:"简体中文"`、通知、项目名、笔记标签只有中文;官网英文下载包每份 2–58 处中文。 |
| M7 | 中 · 已确认 | `loops.py:112-125` | 循环 fail-fast:整片里一镜被审核拦下,前面已付费的视频全部白花。 |
| L | 低 | — | 切片每条新建一个项目;新增模板要同步改 5 处(分派、官网同步脚本、前端图标表、前端写死的 `WorkflowTemplateId`、目录);`_object` 两份;`template_version` 无人读取,已装模板没有升级路径;布景 `max_tokens=16000` 可能截断(推断);切片与精剪把整段逐字稿塞进一次调用,长直播可能超上下文(推断)。 |

测试缺口:没有任何模板在假供应商下完整跑通过一次(`test_official_workflows_walk` 在空工作区多半停在 422);
没有「每段 / 每拍实际时长 = 计划时长」「每拍都有口播与字幕」「互斥素材组」这类产出断言。

---

## 4. 建议(按优先级)

**先修(安全与钱):**

1. **错误文字统一脱敏**:去掉 URL 查询串、`user:pass@`、已展开的 `${KEY}`;`artifacts._download` 只报状态码与主机名。补测试。
2. **MCP 在授权前不执行**:`refresh_tools` / `_pull_tools` 走 `blocked_reason`(至少加 `permissions_granted`)。补测试。
3. **修四个产出错的模板**(§3 H1–H4),并给每个模板加一条假供应商端到端测试,断言产出(时长、口播、字幕、素材组)。
4. **权限的文案如实写**「仅表示同意,不做隔离」,界面去掉像有范围的译文;长期再考虑 sandbox-exec / seccomp 与按域名的出口白名单。
5. **Manim 护栏**检查 `ImportFrom` 的名字(含别名),禁 `ctypeslib` 与 `load*`;反例进测试参数表。
6. **effects 如实**:`storage_presign` 改 external、默认不开;两个 setup 改 external;运行时报出的工具 effects 至少 external、不能自报默认开放。

**再修(可靠性与预算):**

7. budgets 契约加一条:会被智能体就地调用的工具预算 < 180s,否则改开卡或进后台任务;流式工具不占 `PLUGIN_SLOTS`(或分长短两池)。
8. 清单解析对一切类型错误抛 `ManifestError`,扫描 / 装包按单包失败处理;校验 `provides` 词表、未来版本、未知 kind。
9. 默认提供方不可用时报错提示,不静默换一家;关闭时清理插件进程树(Linux 加 `PR_SET_PDEATHSIG`)。
10. 宿主下载产出接上进度与取消;保存连接时的目录刷新改后台异步。
11. 工作流费用上限:用上 `MAX_VARIANTS`,schema 加 `maxItems`;前置检查按模板拆参考图判据;占位值改为空且必填,运行前 422。

**顺手(体验与维护):**

12. 模板的提示词、起始参数、通知按 locale 生成;模板注册表一处定义(同步脚本、前端 id 从它派生),`template_version` 起作用;依赖锁全(remotion lockfile + `npm ci`,manim constraints);Blender 加 `package_sources`;`plugin_kit` 做成宿主提供的 SDK。
