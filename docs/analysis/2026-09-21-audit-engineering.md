# 工程体系审计:守门的那一层,自己谁来守

> 日期:2026-09-21 · 基准:`e58190f2` 工作区(干净)· 版本 1.4.2
> 范围:测试体系、棘轮、契约、迁移、CI 与发布、文档体系。**不含业务代码**。
> 方法:抽查 12 条棘轮的**断言本身**(不是它当下红不红),逐条想清「什么样的改动会绕过它」;
> 实测跑了一遍后端全量(3756 passed / 391.67s);所有数字都是当场量的。
> 本文承接 [2026-09-21 链条审计](2026-09-21-chain-audit.md) §5 留下的三条待办。

---

## 0. 结论先写

链条审计说「现有棘轮覆盖的是"两侧是否一致",覆盖不了"这一环有没有接上"」。**这次量下来,
问题比那句话更靠前一层:有相当一批棘轮连"两侧是否一致"都只覆盖了一半,而且覆盖不到的那一半
是静默的** —— 它不报"我看不懂这一处",它直接跳过。

三件事最要紧:

1. **昨天新写的那条执行器棘轮,今天仍然有一个同形的盲区**,而且盲区里躺着 `llm` 这种主力节点
   (`test_executor_outputs_are_declared.py:80` 只认 `ast.Assign`,不认 `ast.AnnAssign`)。它
   不红不是因为对,是因为**它看不懂就不看了**(`:152` `if keys is None: continue`),而且没有
   任何豁免登记会留下痕迹。
2. **数据库快照这道保险,自 2026-09-04 起实际是关着的。** `DATABASE_SCHEMA_VERSION` 最后一次
   bump 在 `13147ee0`,此后新增了 14 个迁移(含两处 `DROP TABLE` + 搬文件),版本号一次没动 ——
   而 `snapshot_before_upgrade` 在 `current == target` 时直接 `return None`。唯一那条测试
   (`test_database_upgrade_safety.py:20`)**自己先把 user_version 改成 0** 才验,所以它永远绿。
3. **数据归属这条「架构纪律真的在执行」的样板,豁免掉了整个 `app/api/routes/`**
   (`ownership.py:117`),而那下面有 **17 处直接建行**。其中 `assets.py:50` 建 `Asset` 这一处,
   正是另一条棘轮的存量名单里写着「`app/domain/assets/importer.py:唯一实现` —— 假」的那一条。
   **两条棘轮各自绿着,事情掉在它们中间。**

同时要说清楚:这套体系的**形状**是对的,而且好过我见过的绝大多数仓库 —— 102 条棘轮与文档自动
同步、11 份契约两侧都真的在跑、CI 是主干与发版共用的同一份、迁移有显式 phase 与记账。下面挑的
都是「已经建好的机制,边界画在了错的地方」,不是「没建」。

---

## 1. 抽查的 12 条棘轮,逐条结论

判据统一:**假设一个不知情的人做出这条棘轮声称要拦的那种改动,它会不会红。**

### 1.1 `backend/tests/test_executor_outputs_are_declared.py` —— ❌ 能被绕过

昨天新写的那条。它的 docstring 明写「只认 `return {字面量}` 的话,这条棘轮会在它该响的那一次
保持沉默」,并为此补上了「先攒进变量再 return」的识别。**但补的是 `ast.Assign`,漏了
`ast.AnnAssign`**:

```
test_executor_outputs_are_declared.py:80   if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
```

而 `llm` 节点的写法正是带标注的那种:

```
backend/app/domain/workflows/executors/ai.py:407   result: dict[str, Any] = {"text": text}
```

于是 `_literal_keys` 拿到空集 → `_returned_keys` 透传也找不到 → 返回 `None` →
`:152 if keys is None: continue` **静默跳过**。实测(把测试的 helper 直接跑一遍):

| | 实际比对的节点 | 静默跳过的节点 |
| --- | --- | --- |
| 本条棘轮 | 50 | **3**(`llm`、`note_read`、`browser_close`) |

**怎么绕过它**:给 `llm` 加一个新产出键(`result["usage"] = …`),这条棘轮一个字都不会说。

两个更深的毛病:

- **跳过没有登记。** docstring 说「找不到定义的(第三方、动态构造)才登记豁免,并写清楚理由」,
  而 `DYNAMIC` 里只有 3 条手写项,真正被跳过的那 3 个**不在任何名单里** —— 名单越短看着越干净,
  而漏网的数目刚好和名单一样长。旧的那条(§1.2)在同样情况下是**报错**:
  「返回值不是字面量字典,要么改成字面量,要么写进 INDIRECT 并说明」。新的这条退化了。
- **没有「扫到东西」的下界断言。** `_executors()`(`:129`)只认顶层函数上 `register(...)` 这种
  形状;改成 `@registry.register(...)` 或 `@node(...)`,它会扫到 0 个执行器然后绿着通过。
  旧那条有 `assert checked >= 20`(`test_node_outputs_match_the_executor.py:141`),新这条没有。

### 1.2 `backend/tests/test_node_outputs_match_the_executor.py` —— ✅ 真能拦住(但和 1.1 的洞互补)

它认 `ast.AnnAssign`(`:87`),所以 `llm` 归它管;它有下界断言(`:141`);它对看不透的返回是
**报错而不是跳过**。这是两条里更靠谱的那条。

问题在于两条的豁免**不重叠**:

```
node_outputs_match_the_executor.py:26   "note_read",
node_outputs_match_the_executor.py:29   "scene_render",
```

`scene_render` 在它的 INDIRECT 里 —— **这就是昨天那次它没响的原因**,也正是新写 1.1 的理由。
而反过来,`note_read` 同时落在它的 INDIRECT 和 1.1 的静默跳过里:

> **`note_read` 是当前唯一一个两条棘轮都不查的节点。** 它声明了 7 个输出
> (`note_id/title/text/markdown/tags/revision/citation_url`),实际返回
> `{**ref, "text": ref["markdown"]}`(`executors/knowledge.py:52`),键由
> `domain/notes.py:180` 的 `read_reference` 决定。**今天恰好对得上**,但改 `read_reference`
> 的返回形状不会让任何测试变红。

**这是本次审计最该记住的形状**:不是"缺一条检查",是"有两条检查,各自把对方能看见的那块
写进了自己的豁免名单",于是缝隙正好在中间,而两条都绿。

### 1.3 `backend/tests/test_schema_migrations_cover_the_models.py` —— ❌ 能被绕过

它的规则是「模型里的每一列,要么在基线里,要么有一条 ADD COLUMN」。但:

```
test_schema_migrations_cover_the_models.py:52   if table.name not in baseline:
                                          53       continue  # 新表:create_all 会建,列都在 CREATE 里
```

**表不在基线里 = 整张表永久不查。** 实测:模型里 75 张表,基线里 58 张,**17 张表这条棘轮从来
没看过一眼**:

```
activity_events, agent_questions, agent_voice_prefs, boards, comment_mentions, comments,
deployment_config, generation_capability_declarations, generation_capability_profiles,
note_revisions, notes, reviews, scene_3d_models, scene_3d_revisions, scenes_3d,
session_groups, workflow_revisions
```

「新表的列都在 CREATE 里」这个理由**只在这张表刚建出来的那一天成立**。证据是这 17 张里已经有
至少 4 张后来需要手写 ALTER 迁移:

```
backend/app/db/migrations.py:1740   ALTER TABLE boards ADD COLUMN revision ...   (_migrate_board_revision)
backend/app/db/migrations.py       comments ×2、session_groups ×1、deployment_config ×1
```

也就是说:**`boards.revision` 那条迁移是靠人想起来写的,不是靠棘轮逼出来的** —— 而这条棘轮
存在的全部理由就是"不该靠人想起来"(它的 docstring 原话:「它不该靠人发现 —— 发现它的地方是
用户的启动日志」)。

叠加风险:`scene_3d_models` 在这 17 张里,而它的表结构是**手抄在迁移里重建**的:

```
backend/app/db/migrations.py:1630   "CREATE TABLE scene_3d_models_new (" ... 六列手写
```

将来给 `Scene3DModel` 加一列:`create_all` 不会给已存在的表加列 → 这份手写 CREATE 也不会有它
→ 基线不含这张表所以棘轮不查 → **升级的机器上少一列,新装的机器正常**。三道防线全部失效,
而这正是这条棘轮 docstring 里写的那两个真实事故的形状。

**修法(便宜)**:把这 17 张表补进 `tests/schema_baseline.json`,并把 `:52` 那个 `continue`
改成"没登记基线 = 红,请把新表的列写进基线"。

### 1.4 `backend/tests/test_data_ownership_ratchet.py` —— ⚠️ 检查本身很硬,但豁免掉了出事的那一层

这条棘轮的**写法**是全仓最好的一条:双向(有归属的模型 / 归属里没死表)、ALLOWLIST 是空集、
修好一处必须同步删名单。但:

```
backend/app/domain/ownership.py:117
EXEMPT_PREFIXES = ("app/api/routes/", "app/db/", "app/api/schemas/")
# 路由层与测试不受限:路由是薄转译(建实体前已被鉴权链把关)
```

实测 `app/api/routes/` 下有 **17 处直接构造并落库**:

| 文件 | 建的行 |
| --- | --- |
| `routes/assets.py:52` | `Asset` |
| `routes/auth.py:60 / :95 / :294` | `User`、`RegistrationInvite`、`WorkspaceMember` |
| `routes/projects.py:16 / :19 / :39` | `Workspace`、`WorkspaceMember`、`Project` |
| `routes/oauth.py:241 / :249` | `User`、`OAuthIdentity` |
| `routes/sequences.py:126–128` | `Sequence`、`Track` ×2 |
| `routes/generation.py:38`、`routes/feishu.py:32`、`routes/voices.py:306`、`settings/*` ×4 | … |

豁免的理由写的是「路由是薄转译」,而 `assets.py` 那一处并不薄:

```python
# backend/app/api/routes/assets.py:50
@router.post("/assets", response_model=AssetOut)
def create_asset(body: AssetCreate, db: DbSession, user: CurrentUser) -> Asset:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    asset = Asset(**body.model_dump())
    db.add(asset); db.commit(); db.refresh(asset)
```

**而这件事仓库自己已经知道了**,写在另一条棘轮的 docstring 里:

```
test_single_point_claims_name_their_guard.py 开头
    app/domain/assets/…   「入库的唯一实现」   假(POST /api/assets 直接建行)
```

于是:A 棘轮把它写进存量名单当已知债务,B 棘轮把它所在的整个目录豁免掉。**两边都绿,而
ADR-0003 与 ARCHITECTURE.md:218 仍然写着「行创建只发生在拥有方,棘轮测试强制」。**

### 1.5 `backend/tests/test_subprocess_has_one_door.py` —— ❌ 能被绕过

声称「外部命令只从一个口子出去」,实际只认一种形状:

```
test_subprocess_has_one_door.py:38   and func.attr == "run"
```

看不见的写法:`subprocess.Popen`、`check_output`、`check_call`、`call`、
`from subprocess import run` 之后裸调 `run(...)`、`os.system`、`asyncio.create_subprocess_exec`。

**而 Popen 恰恰是已经漏过一次的那个**,证据在门本身的注释里:

```
backend/app/core/child_process.py:46
  `subprocess.run` 那条路早就收进了 `run_logged`,而常驻/流式的那些一直在各自裸调 `Popen`
```

门修好了(`popen_text`,`child_process.py:43`),**守门的棘轮没跟上**。今天实测 `app/` 下没有
新的越界(只有两处类型标注),所以是"暂时没事",不是"拦得住"。

附带:它的扫描根是 `pathlib.Path("app")`(`:32`),**跟着 cwd 走**。CI 是 `cd backend && pytest`
所以没事;从仓库根跑 pytest 时 `app/` 不存在 → `rglob` 返回空 → **一个文件都没扫,测试绿**。
同样形状的还有 5 条:`test_agent_identity_ratchet.py`、`test_frozen_build_is_not_a_python_interpreter.py`、
`test_schema_migrations_cover_the_models.py`、`test_text_io_never_inherits_the_platform_encoding.py`、
`test_write_permission_is_explicit.py`。

### 1.6 `backend/tests/test_sqlite_connections_are_closed.py` —— ✅ 真能拦住

形状匹配精确(`_is_sqlite_connect` 只认 `sqlite3.connect`,裹了 `closing()` 自然不匹配),
ALLOWLIST 是空集且双向校验。唯一盲区是"先赋值再 `with`"(`conn = sqlite3.connect(...)`;
`with conn:`),实测 `app/` 下 0 处。

值得留一句:它只扫 `app/`,而 `tests/` 里有 5 处不安全写法
(`test_database_upgrade_safety.py:19/28/33`、`test_data_management.py:78/148`)。测试只在
mac/Linux 跑,所以无害 —— 但那正是这条棘轮 docstring 所说的「mac 开发机和 Linux CI 一起给它
放行」的环境。

### 1.7 `backend/tests/test_cross_runtime_claims_name_a_contract.py` —— ✅ 真能拦住,全仓最稳的一条

它是唯一一条**把自己的失效方式写进断言**的:

```
test_cross_runtime_claims_name_a_contract.py:120
def test_the_scan_actually_finds_things() -> None:
    """措辞表和目录写错了会让这条测试永远绿 —— 一条永远绿的棘轮比没有更糟。"""
    assert len(_claims()) >= 5
```

而且它的 docstring 诚实地写明了自己挡不住什么(换个新说法就漏)。**这条该当模板。**
实测:后端 67 条棘轮里,只有 **14 条**有任何形式的「扫到东西」下界断言。

小盲区:`SKIP_NAME_PARTS = ("parity", "contract")`(`:85`)是按**文件名**跳过的,所以一个
业务文件只要名字里带 `contract`(如 `contractRules.ts`)就整份不扫。

### 1.8 `backend/tests/test_single_point_claims_name_their_guard.py` —— ⚠️ 半条

思路对(说了「唯一实现」就得点名守卫),但 `GUARD_HINT`(`:56`)只是一个正则:
**点名的那个测试文件存不存在,没人验。** 写 `见 tests/test_nothing.py` 即可让任何"唯一实现"
的断言过关。实测当前没有这种假引用(扫了 `app/` 下全部注释,0 处指向不存在的测试),所以是
潜在漏洞而非现实漏洞。

真正的问题是前面 §1.4 说的:ALLOWLIST 里 `app/domain/assets/importer.py:唯一实现` 那条,
docstring 自己标注为"假",却以"存量"的身份被冻结着 —— **一句已知为假的注释,被一条棘轮
正式许可继续留在代码里**。棘轮的作用应该是让假话出局,不是给它发居住证。

### 1.9 `backend/tests/test_docs_do_not_point_at_ghosts.py` —— ❌ 能被绕过(且已经被绕过了)

```
test_docs_do_not_point_at_ghosts.py:26
PATH_RE = ((?:backend|frontend|electron|plugins|scripts|website)/[\w./-]+\.(?:tsx|mdx|…|md))
```

**两个硬条件:必须有仓库根前缀,必须有文件后缀。** 而文档里最常见的写法恰好两条都不满足 ——
模块路径和目录路径。实测四处**当前正在骗人**的引用:

| 文档 | 写的 | 实际 |
| --- | --- | --- |
| `docs/ARCHITECTURE.md:375` | `domain/ai_retry.RetryingClient` | 已搬到 `backend/app/core/http_retry.py`(靠 `as ai_retry` 别名活着) |
| `docs/ARCHITECTURE.md:484` | `components/agent/`(57 个文件) | 目录不存在,整块在 `frontend/src/features/agent/` |
| `docs/MAINTENANCE_HOTSPOTS.md:444` | 三个页面都渲染 `components/agent/CanvasAgentChat.tsx` | `frontend/src/features/agent/CanvasAgentChat.tsx` |
| `docs/ARCHITECTURE.md`(浮动面板一节) | `features/workflows/useFloatingPanel.tsx` | `frontend/src/components/app/useFloatingPanel.tsx` |

还有 `ai/providers/media_transfer.py`(实为 `app/ai/media_transfer.py`)、`audio/remote_size.py`
(实为 `app/ai/runtime/remote_size.py`)。**同一个 `domain/ai_retry` 的幽灵还长在代码注释里**
(`app/core/usage_scope.py:15`、`app/api/routes/settings/system.py:68`)。

**修法**:把 `PATH_RE` 的根前缀改成可选,匹配到没有前缀的就依次去 `backend/`、`frontend/src/`、
`backend/app/` 下找;目录路径(以 `/` 结尾)同样查。这是一条一行的改动,能一次性抓出上面全部六处。

### 1.10 `frontend/src/lib/typeScale.test.ts` —— ❌ 能被绕过,而且它的理由本身已经过期

```
typeScale.test.ts:38   matchAll(/text-\[([0-9.]+px)\]/g)
```

只认 `text-[NNpx]`。看不见的:

- **Tailwind 自带的 `text-xs / text-sm / text-base / text-lg / …`:实测 `frontend/src/` 下 218 处**,
  而 `tokens.css` 并没有重定义它们,所以它们是**第二套字号刻度**,和约定说的「四档 `text-ui-*`」
  并行存在;
- `text-[0.8rem]`(`frontend/src/components/ui/form.tsx:142 / :164`)—— 单位不是 `px` 就看不见,
  而且它**不在 `ALLOWED` 里**,也就是说这个例外不在"看得见的清单"上;
- 内联 `style={{ fontSize }}`。

更值得记的是**理由过期**:

```
typeScale.test.ts:8  「现在四档 text-ui-* 用 clamp() 跟视口联动(1280 宽处等于原来的像素值)」
frontend/src/design/tokens.css:43  /* One desktop type scale … Viewport size changes layout,
                                      not the font size of the same control. */
tokens.css:45-50   --text-ui-2xs: 11px; … --text-ui-title: 32px;   ← 没有一个 clamp()
```

代码里一个 `clamp(` 都没有,而且 CSS 自己的注释写的正好相反。棘轮的断言还对(硬编码 px 确实
该拦),**但它给出的理由是假的,而理由正是下一个人判断"这条还要不要"的依据**。顺带:
`docs/CONVENTIONS.md` 与这条 docstring 都说"四档",实际是六个 token。

### 1.11 `frontend/src/design/apiSeam.test.ts` —— ✅ 真能拦住,但余量只剩 2

阈值式棘轮。实测(按它自己的算法跑):当前 **158**,`BASELINE = 160`(`:19`)。余量 2 ——
再加第三处手拼路由就会红。这是阈值式棘轮**健康**的样子;需要注意的只是余量是会被悄悄用掉的
资源,迁走一块就要记得把数字改小(它的注释已经这么写了)。

### 1.12 `frontend/src/design/agentTypeScale.test.ts` —— ✅ 真能拦住

昨天新写的那条。它断言的是**常量本身**(`AGENT_ROW_*` 必须自带字号、三处同档、比正文小一档),
外加**消费点**(`ToolCalls.tsx` 必须挂上那个常量、`toolResultShapes.tsx` 不许出现 `text-ui-md`)。
"定义 + 消费点"两头都钉住,是本次抽查里唯一一条覆盖了"这一环有没有接上"的。可以当模板。

### 小结表

| 棘轮 | 结论 | 绕过方式 |
| --- | --- | --- |
| `test_executor_outputs_are_declared.py` | ❌ | `result: dict = {...}`(AnnAssign)→ 静默跳过;register 改形状 → 扫 0 个仍绿 |
| `test_node_outputs_match_the_executor.py` | ✅ | INDIRECT 里的 10 个不查;与上条的洞互补,`note_read` 掉在缝里 |
| `test_schema_migrations_cover_the_models.py` | ❌ | 表不在基线 → 整表不查(17/75 张) |
| `test_data_ownership_ratchet.py` | ⚠️ | 检查很硬,但 `app/api/routes/` 整目录豁免,下面有 17 处建行 |
| `test_subprocess_has_one_door.py` | ❌ | `Popen` / `check_output` / `from subprocess import run` |
| `test_sqlite_connections_are_closed.py` | ✅ | 先赋值再 `with`(实测 0 处) |
| `test_cross_runtime_claims_name_a_contract.py` | ✅ | 换个没收录的措辞;文件名带 parity/contract 整份跳过 |
| `test_single_point_claims_name_their_guard.py` | ⚠️ | 点名一个不存在的测试文件即可过关 |
| `test_docs_do_not_point_at_ghosts.py` | ❌ | 不带仓库根前缀或不带后缀的路径 —— **已有 6 处真实幽灵** |
| `lib/typeScale.test.ts` | ❌ | Tailwind 原生字号档(218 处)、rem 单位、内联 fontSize |
| `design/apiSeam.test.ts` | ✅ | 阈值余量 2 |
| `design/agentTypeScale.test.ts` | ✅ | —— |

---

## 2. 问题清单(按严重度)

### P0-1 数据库升级快照,实际已经关了 17 个版本

**现象**。`init_db` 在跑迁移前会存一份整库快照当保险:

```
backend/app/db/migrations.py:1671   snapshot_before_upgrade(settings.db_path, target_version=DATABASE_SCHEMA_VERSION)
backend/app/db/safety.py:78         if current_version == target_version or not has_schema: return None
backend/app/db/safety.py:24         DATABASE_SCHEMA_VERSION = 3
```

`DATABASE_SCHEMA_VERSION` 最后一次 bump 是 `13147ee0`(2026-09-04,1→2→3 都在那两天)。此后
`migrations.py` 改了 17 次,**新增了 14 个迁移**,包括:

```
_migrate_scene_models_to_disk          搬文件 + ALTER
_migrate_scene_models_to_workspace     DROP TABLE + RENAME + 搬目录   ← 本周做的
_migrate_scene_cameras_become_objects  改写每条场景的 JSON
_migrate_line_fields_are_lists / _migrate_job_keys_are_keys / _migrate_clip_offline_asset / …
```

任何一台从 2026-09-04 之后的版本升上来的机器,`user_version` 已经是 3 = 目标值 →
**`snapshot_before_upgrade` 直接返回 None,一份快照都不存**,然后 DROP TABLE 就开始了。

**为什么看不出来**。唯一守它的测试**自己先把状态位改掉**:

```
backend/tests/test_database_upgrade_safety.py:20   database.execute("PRAGMA user_version = 0")
```

于是这条测试验的是"机制能不能工作",而不是"这一版它会不会工作"。机制没坏,**开关关着**。
(这正是 `MEMORY.md` 里那条「断言状态位要按『东西在哪』查」的同一个形状:空容器上的标记
天然满足断言。)

**为什么是体系问题**。`safety.py:22` 的注释写着「Bump this exactly when startup migrations
change the persistent database shape」—— 这是一条纯靠人记的规矩,写在一个每次改迁移都不必打开的
文件里,而仓库对"靠人记的规矩"的标准答案是上棘轮。17 次机会,0 次被提醒。

**建议修法**。不要再让人记版本号 —— 让它**从迁移计划自己算出来**:

```python
# safety.py
def schema_fingerprint() -> str:
    return hashlib.sha256("\n".join(s.name for s in migration_plan().steps if s.once).encode()).hexdigest()[:16]
```

把 `user_version` 换成"已记账迁移集合的指纹",`schema_migrations` 表里已经有这个集合了 ——
**计划里多一个一次性步骤 = 指纹变 = 快照照存**,不需要任何人记得。过渡期最省事的版本:一条
棘轮,断言 `DATABASE_SCHEMA_VERSION` 必须 ≥ 一次性迁移的条数(现在 69 > 3,当场红)。

### P0-2 一条在该响时沉默的棘轮,今天仍然沉默

见 §1.1。**现象**:`test_executor_outputs_are_declared.py` 看不懂 `result: dict[...] = {...}`
(`ai.py:407`,`llm` 节点),于是 `:152` 静默 `continue`;实测 50 查 / 3 跳,跳过的不进任何名单。

**为什么看不出来**:跳过和"查过并且没问题"在测试输出里是同一个绿点。

**为什么是体系问题**:这是**同一个 bug 的第二次**。昨天修的是「只认 `return {字面量}`」,
今天漏的是「只认 `ast.Assign`」—— 补的还是"那一处",不是那个概念。那个概念是:
**一条静态扫描的棘轮,凡遇到看不懂的输入,必须报错,不能跳过**;跳过是把判断权交给了
"这次恰好写成什么形状"。

**建议修法**(三条,都很小):

1. `:152` 的 `continue` 改成收集进 `unreadable` 列表并断言为空,豁免必须写进 `DYNAMIC` 并给理由
   —— 和旧那条(`test_node_outputs_match_the_executor.py`)的做法对齐;
2. `_literal_keys` 加上 `ast.AnnAssign`(旧那条 `:87` 已经这么写了,**直接抄过来**);
3. 补 `assert checked >= 45`。

顺带:两条棘轮守同一件事、豁免名单互不相交、缝里漏着 `note_read` —— **该合并成一条**,
取两边的并集(AnnAssign + 透传解析 + 下界断言 + 看不懂就报错)。合并的判据很清楚:现在
没有任何人能一眼说出"这个节点归哪条管"。

### P1-1 数据归属:样板棘轮豁免了出事的那一层

见 §1.4。**现象**:`ownership.py:117` 豁免 `app/api/routes/`,而那下面有 17 处直接建行,其中
`assets.py:52` 已被另一条棘轮的 docstring 记为"假"。

**为什么看不出来**:豁免写在**被检查方**(`domain/ownership.py`)而不是检查方,读棘轮测试的人
看不到它;而豁免的理由("路由是薄转译")在写下时可能是真的。

**为什么是体系问题**:ADR-0003、`ARCHITECTURE.md:218`、链条审计 §4「没有发现问题的地方」
三处都把"棘轮强制"当成既成事实。**一个被普遍相信的保证,和一个没有的保证,不是同一种风险 ——
前者更坏**,因为它让人不再去看。

**建议修法**:不必一次清完 17 处。把 `app/api/routes/` 从 `EXEMPT_PREFIXES` 拿掉,把现存 17 处
写进 `ALLOWLIST`(只减不增)。这样"已知债务"是**一份看得见、会被数的清单**,而不是一个让整层
消失的前缀;同时同步修正 ARCHITECTURE.md 那句话的口径。

### P1-2 进程级全局状态在测试之间串台,并且吃掉了 13% 的套件时间

**现象**。全量实测:3756 passed / 391.67s,**最慢 45 条合计 199.2s = 全套 50.8%**;最慢一条:

```
49.52s   tests/test_provider_models.py::test_comfyui_连不上时目录为空而不是报错
```

它连的是 `http://127.0.0.1:1`,应该毫秒级拒绝。单独跑只要 4.68s(3 次退避)。现场复现:

```
$ pytest tests/test_provider_models.py::test_comfyui_连不上时目录为空而不是报错
  4.68s
$ pytest tests/test_llm_retry.py tests/test_provider_models.py::test_comfyui_连不上时目录为空而不是报错
 26.37s      ← 同一条测试,5.6 倍
```

肇事者:

```
backend/tests/test_llm_retry.py:144   client.put("/api/settings/ai-runtime", json={"max_retries": 6})
backend/app/core/http_retry.py:19     DEFAULT_MAX_RETRIES = 3        # 进程级 _max_retries
```

那个 PUT 走的是真实设置接口,把**进程级**的 `_max_retries` 改成 6 并且**没有人改回来**。全量里
它涨到 49.5s,说明还有别处把它推得更高(`test_who_owns_each_setting.py:180` PUT 了 9)。

**为什么看不出来**:测试全绿,只是慢;而"慢"在 3756 个点里是看不见的。

**为什么是体系问题**:`docs/PROCESS_STATE.md:53` **已经登记了这条状态**,
`test_process_state_inventory.py` 还在强制这份清单的完整性。也就是说体系做到了"把进程级状态
写下来",但没有做到"测试之间把它还原" —— **登记本身制造了一种已受控的错觉**。16 条登记的
进程级状态,目前没有任何一条有重置 fixture(`tests/conftest.py` 只重置后台线程)。

**建议修法**:`conftest.py` 加一条 autouse fixture,把 `PROCESS_STATE.md` 登记的那几处可变状态
在每条测试后还原;并给 `test_process_state_inventory.py` 加一条断言:清单里的每一项要么有重置
钩子,要么写明为什么不需要。顺带能省下套件里的一大块时间。

### P1-3 「接口字段 → 前端消费点」这一跳,没有任何检查,而且已经在漏

链条审计 §5 建议补两条棘轮,其中一条是这个。实测量了一下漏的规模:

> 扫 `app/api/schemas/*.py` 里所有 `*Out` / `*Response` 的字段(431 个),再在
> `frontend/src/` 全部手写 TS/TSX 里找它(含 camelCase 变体):**38 个字段前端一次都没出现过**,
> 只活在 `api/generated/schema.d.ts` 里。

名单里最刺眼的两个:

```
backend/app/api/schemas/scenes.py:52   skipped_models: int        ← 昨天那条链上的值
backend/app/api/schemas/scenes.py:54   model_warnings: list[str]
```

昨天补的是 `NODE_TYPES["scene_render"]["outputs"]`(工作流那条路),**而 API 这条路上这两个字段
至今没有任何前端消费点** —— `POST /scenes/{id}/shots/{id}/references`(`routes/scenes.py:128`)
在 `frontend/src/` 里找不到调用方。其余 36 个里还有
`jobs.py:JobOut.message_key / message_params / error_key / error_params`(一整套 i18n 载荷)、
`dashboard.py:WorkspaceSummaryOut` 的 7 个 usage_* 字段、`sequences.py:ClipOut.linked_clip_id`。

**为什么看不出来**:`openapi.json → schema.d.ts` 那道 CI 闸(`tests.yml`「OpenAPI snapshot …
are fresh」)保证的是**类型跟得上**,不是**有人用**。类型生成得越及时,"这个字段已经接通了"
的错觉越强。

**为什么是体系问题**:这正是链条审计说的"N-1 环都在,最后一环没接上"。而它的第一步很便宜 ——
上面那段扫描三十行就能写成一条棘轮,基线 38 只减不增。

**建议修法**:新棘轮(拟名 responseFieldsAreConsumed.test.ts，放在 frontend/src/design/ 下),把当前 38 个冻进
`ALLOWED` 并各写一句"为什么不用"(有些确实是给智能体/工作流的,不给界面 —— 那就写下来,
它立刻变成一份可读的分工说明,而不是一批来历不明的字段)。

### P2-1 46/69 个迁移,只跑过"无事可做"那条分支

**现象**。`migration_plan()` 里 69 个步骤,实测只有 **23 个**在 `backend/tests/` 里被任何测试
点过名;另外 46 个**没有任何一份老形状的数据喂给它们**。它们确实每条测试都在跑
(`fresh_client()` → `init_db()`),但那是空库 —— BEFORE_SCHEMA 的迁移第一行就 `if 表不存在:
return`,跑的是 no-op 分支。

有专门测试的那 5 个写得很好,而且都验了可重入(`test_scene_models_move_to_disk_migration.py`
的 `test_running_it_again_is_a_no_op`、`..._to_workspace_migration.py` 的 `test_跑第二次不炸`)。
**问题不是没人会写,是没有东西在要求写。**

**为什么是体系问题**:仓库对迁移的纪律是「不写兼容代码,旧数据用迁移」(ADR-0006 + `MEMORY.md`)。
这条纪律把**全部**兼容风险押在迁移的正确性上,而迁移的正确性目前是 1/3 覆盖。

**建议**:给 `_steps(...)` 加一个"有没有对应测试"的棘轮(基线 46 只减不增),新加的迁移必须带
一条喂旧形状的测试。这和 `test_schema_migrations_cover_the_models.py` 是同一种做法,只是换个维度。

### P2-2 记账表没有内容指纹:修好的迁移在老机器上永远不会重跑

```
backend/app/db/migration_runner.py:99   CREATE TABLE schema_migrations (name …, applied_at …)
```

记的是**名字**。如果某个迁移有 bug 但没抛异常(比如漏搬一部分行),它会被记成 applied;
后来修好代码,**已经记过账的机器不会再跑它**,而这正是需要重跑的那些机器。现在唯一的补救是
改函数名,而那要同时改 `_steps` 生成的稳定标识——一个很容易被当成"重构"而拒绝的改动。

**建议**:记账行加一列 `body_sha`(函数源码哈希),不一致时重跑。对幂等的迁移这是免费的,
而"迁移必须幂等"已经是这套体系的既有前提。

### P2-3 发布:RELEASING.md 说"官网测试会逐项核对",实际只核对了 5 处中的 2 处

```
docs/RELEASING.md:11   版本号要改的地方不止 package.json。官网的测试会逐项核对,漏一处就红在 '1.3.0' !== '1.3.1'
```

实测对照 `website/test/documentation-media.test.mjs`:

| RELEASING.md 列的位置 | 有测试吗 |
| --- | --- |
| `capture-manifest.json` 的 `documentedVersion` | ✅ `documentation-media.test.mjs:14` |
| 每篇 mdx frontmatter 的 `version` | ✅ `documentation-media.test.mjs:43` |
| 中英下载页正文的「已正式发布」 | ❌ 无(`content/docs/zh/start/download.mdx:27`、`en/…:26`) |
| `website/README.md` 的「当前文档对应」 | ❌ 无(`website/README.md:76`) |
| `website/src/lib/release-copy.ts` 这一版的中英亮点 | ❌ 无 |

还有两处正文里的版本号连清单都没列到:`content/docs/zh/about/project.mdx:42`(「文档适用于 1.4.2」)、
`content/docs/en/guides/workflows.mdx:19`(「Use v1.4.2 or」)。

**为什么是体系问题**:这句话的作用是让发版的人**不用逐个去查**。它比"什么都不写"更危险 ——
漏掉下载页正文的版本号,CI 会绿,用户会在官网上看到"1.4.2 已正式发布"而当前是 1.4.3。

**建议**:给 `website/test/` 补一条:全仓扫 `X.Y.Z` 形状的字面量,凡落在白名单文件里的都必须
等于 `package.json` 的 version(`CHANGELOG.md`、历史 release-copy 条目、截图批次的 `version`
除外 —— 后者按 RELEASING.md 的说明**故意**不跟版本走)。同时把 RELEASING.md 那句话改成实话。

### P2-4 `test_docs_do_not_point_at_ghosts` 的正则太窄,已有 6 处真实幽灵

见 §1.9。一行正则的改动能一次抓出全部。列出来方便直接修:

```
docs/ARCHITECTURE.md:375   domain/ai_retry.RetryingClient       → backend/app/core/http_retry.py
docs/ARCHITECTURE.md:484   components/agent/(57 个文件)        → frontend/src/features/agent/
docs/ARCHITECTURE.md       features/workflows/useFloatingPanel.tsx → frontend/src/components/app/useFloatingPanel.tsx
docs/ARCHITECTURE.md       ai/providers/media_transfer.py       → backend/app/ai/media_transfer.py
docs/ARCHITECTURE.md       audio/remote_size.py                 → backend/app/ai/runtime/remote_size.py
docs/MAINTENANCE_HOTSPOTS.md:444  components/agent/CanvasAgentChat.tsx → frontend/src/features/agent/CanvasAgentChat.tsx
代码注释同病:app/core/usage_scope.py:15、app/api/routes/settings/system.py:68 也写着 domain/ai_retry
```

### P3-1 文档里的数字,凡是手写的都已经错了

`docs/CONVENTIONS.md` 的棘轮清单由脚本生成,实测 `--check` 通过(102 条,67 后端 + 35 前端/electron)。
**而同一份文档体系里手写的数字,抽查全错**:

| 位置 | 文档说 | 实际 |
| --- | --- | --- |
| `ARCHITECTURE.md:222` | 53 个 ORM 类分在 `model_slices/` 的 20 个文件 | **75 个 / 25 个文件** |
| `ARCHITECTURE.md:222` | 204 个 schema 分在 `api/schemas/` 的 24 个文件 | **273 个 / 25 个文件** |
| `ARCHITECTURE.md:375` | 21 个模块直接 import `domain/ai_retry` | 模块已不存在;引用 `RetryingClient` 的是 **23** 个文件 |
| `ARCHITECTURE.md:484` | `components/agent/`(57 个文件) | 目录不存在 |
| `MAINTENANCE_HOTSPOTS.md:225` | 822 个后端测试全绿 | **3756** |
| `MAINTENANCE_HOTSPOTS.md:149` | `Editor` 还剩 37 处 useQuery/useMutation | 未核(同一份文档的其他数字已全错,不必再数) |
| `CONVENTIONS.md` / `typeScale.test.ts` | 字号"四档" | 六个 token(`2xs/xs/sm/md/lg/title`) |

**规律很干净**:`docs/` 里凡是有生成脚本的(CONVENTIONS 的棘轮清单、MCP.md 的工具清单、
PLUGIN_MANIFEST、插件市场索引、官网工作流)**全部在同步**;凡是手写的叙述性文档
(ARCHITECTURE.md、MAINTENANCE_HOTSPOTS.md、3D_SCENES.md、KNOWLEDGE_WORKFLOWS.md、adr/、
analysis/)**必然漂移,只是漂多久的问题**。

**建议**:不是给这些文档补测试(散文测不了),而是**把可证伪的部分挤出去**:数目一律不写死,
改成「见「某个脚本 --count」」或干脆删掉。一个数字写在散文里,它唯一的作用是
在一年后骗人 —— 而它提供的信息("大概几十个")去掉数字也一样成立。

### P3-2 棘轮的"理由"没有任何同步机制

`scripts/sync-ratchet-docs.py:63` 只取 docstring 的**第一行**进表格。棘轮 docstring 的正文
(为什么存在、防的是哪次真实事故、挡不住什么)是这套体系里**信息密度最高的一批文字**,而且
没有任何检查 —— §1.10 的 `typeScale.test.ts` 已经证明它会和代码说反话。

没有便宜的技术解。可行的约定:凡 docstring 里写了"现在的做法是 X"(而不是"曾经出过 Y 事故"),
就必须点名守着 X 的那个文件 —— 复用 `test_single_point_claims_name_their_guard.py` 的形状。

---

## 3. 没有发现问题的地方

沿着走过、确认成立的:

- **契约(11 份)确实两侧都在跑,没有单侧孤儿。** 逐份核过消费方:`audio-mix`、`clip-appearance`、
  `clip-free-element-geometry`、`marker-shortcut`、`scene-3d`、`scene-cases`、`shared-constants`、
  `subtitle`、`transform`、`workflow-field-activation` 的另一侧在前端,`context-meter` 在
  `agent-sidecar/test/context-meter.parity.test.mjs`。`scene-3d` 两侧的 docstring 还互相点名了
  对方的文件路径。
- **契约的"找不到语料就静默跳过"已经被堵住。** `test_scene_3d_parity.py:44`
  `test_语料在_而且有内容` —— 这正是 §1.1 里那条新棘轮缺的东西,说明这个意识在仓库里已经有了,
  只是没有推广成规矩。
- **迁移的 phase 划分是对的。** 逐条核过所有 `CREATE TABLE` / `RENAME TO` / `DROP TABLE`:
  8 处里 7 处在 BEFORE_SCHEMA(必须在 `create_all` 之前),唯一在 AFTER_SCHEMA 的
  `_backfill_plugin_instances`(`migrations.py:2011`)做的是回填完成后删 `*_legacy` 表 ——
  顺序正确。`MigrationPlan._validate`(`migration_runner.py:66`)强制 phase 不许回退、名字不许
  重复,这两条都真的在跑。
- **记账机制本身的不变式钉得很死。** `test_migration_ledger.py` 三条:跑过的不再跑、**失败的
  不记账**、对账型(`once=False`)每次都跑且不进表。`_create_current_schema` 被正确标成
  recurring —— 记账跳过它的话新版本的新表就再也建不出来,这是个很容易犯的错,这里没犯。
- **`sqlite3.connect()` 的 `with` 陷阱清零。** `app/` 下 0 处越界,ALLOWLIST 是空集,
  `db/safety.py` 每一处都显式 `closing()`。这条防的是一个只在 Windows 上现形的真实事故。
- **CI 与本地是同一套,而且 CI 严格覆盖本地。** `ci.yml` 与 `release.yml` 共用
  `tests.yml`(`workflow_call`),注释里明写了为什么不能写两份。CI 比本地多跑的部分是
  **本地跑不到的那些**:OpenAPI 快照与 `schema.d.ts` 的新鲜度、agent-sidecar、electron
  typecheck、浏览器扩展、官网 build。而且它显式装 ffmpeg、显式等 docker 就绪并
  `docker pull python:3.13-alpine`,理由写得很清楚:**不装的话 9 个测试文件整体 skip,
  闸看着是绿的而最该验的部分没验**。这是全仓最成熟的一块。
- **发版工作流的"假红叉"处理是对的。** `release.yml` 的 `signing` job 对缺云端公证凭据这件事
  不再 fail 而是 skip 下游并留 notice,理由写着「假红叉比没有红叉更坏:它教人忽略这个工作流的
  红色」。这和本报告 P0-1 是同一条原则的两面。
- **确实有"整条链"的测试,不全是单点。** `test_translated_dub_pipeline.py::test_整条链路跑完之后时间线上该有什么`、
  `test_export_flow.py`、`test_generation_scheduler_flow.py::test_设置页加了什么_生成页就有什么`、
  `test_loop_concurrency_and_full_video_assembly.py`、`test_sequence_flow.py`、`test_subworkflow.py`。
  它们也确实贵(生成调度那条 32.67s),但那是该花的钱。
- **测试套件没有明显的重复覆盖。** 397 个文件 / 2324 个测试函数 / 3756 个用例,唯一发现的重复是
  §1.1–1.2 那两条执行器棘轮 —— 而它们的问题恰恰不是重复,是**两份都不全**。
- **测试成本结构健康。** 391.67s / 3756 = 平均 0.10s;长尾里除了 P1-2 那条被全局状态污染的,
  其余都是真在做事(起子进程、跑渲染、等超时语义)。**没有发现"跑得慢又没价值"的测试。**

---

## 4. 一条贯穿的话

这次找到的东西,可以压成一句:

> **这套体系已经学会了"把规矩变成会红的检查";还没学会"检查看不懂的时候必须喊出来"。**

`test_executor_outputs_are_declared.py:152` 的 `continue`、
`test_schema_migrations_cover_the_models.py:52` 的 `continue`、
`ownership.py:117` 的 `EXEMPT_PREFIXES`、`safety.py:78` 的 `return None` ——
四处形状完全一样:**遇到不认识的情况,选择沉默**。而沉默在测试输出里和"查过了,没问题"
长得一模一样。

对应的解法也只有一条,而且仓库里已经有现成样板
(`test_cross_runtime_claims_name_a_contract.py:120` 的 `test_the_scan_actually_finds_things`):

1. 看不懂就报错,要豁免就写进名单并给理由;
2. 名单只减不增,而且**名单的长度本身要被断言**;
3. 扫描类的检查必须断言"扫到了东西",下界写死。

后端 67 条棘轮里目前做到第 3 条的有 14 条。把这三条补齐,是本次所有建议里性价比最高的一项。

---

## 附:关键文件

**棘轮与体系**
- `scripts/sync-ratchet-docs.py` — 棘轮清单生成器(只取 docstring 第一行)
- `docs/CONVENTIONS.md` — 约定 + 生成的 102 条棘轮清单
- `backend/tests/test_executor_outputs_are_declared.py:80 / :152` — AnnAssign 盲区与静默跳过
- `backend/tests/test_node_outputs_match_the_executor.py:26 / :29 / :87 / :141` — 互补的豁免与下界断言
- `backend/tests/test_cross_runtime_claims_name_a_contract.py:120` — 该当模板的"扫到东西"断言
- `backend/tests/test_schema_migrations_cover_the_models.py:52` — 基线之外整表不查
- `backend/tests/test_subprocess_has_one_door.py:38` — 只认 `subprocess.run`
- `backend/tests/test_docs_do_not_point_at_ghosts.py:26` — 路径正则太窄
- `backend/tests/test_single_point_claims_name_their_guard.py` — 点名的守卫不校验存在
- `frontend/src/lib/typeScale.test.ts:38` + `frontend/src/design/tokens.css:43-50` — 断言对、理由假
- `frontend/src/design/agentTypeScale.test.ts` — "定义 + 消费点"两头钉住的样板
- `frontend/src/design/apiSeam.test.ts:19` — 阈值式棘轮,余量 2

**迁移与数据库**
- `backend/app/db/safety.py:24 / :78` — `DATABASE_SCHEMA_VERSION` 与"相等就不快照"
- `backend/app/db/migrations.py:1671` / `:1630` / `:2154` — 入口、手抄的 CREATE TABLE、迁移计划
- `backend/app/db/migration_runner.py:66 / :99` — phase 校验与记账表(无内容指纹)
- `backend/tests/test_database_upgrade_safety.py:20` — 自己把状态位改成 0 的那条断言
- `backend/tests/schema_baseline.json` — 58/75 张表
- `backend/app/domain/ownership.py:117` — `EXEMPT_PREFIXES`
- `backend/app/api/routes/assets.py:50` — 被两条棘轮同时放过的那处建行

**契约**
- `contracts/README.md` + 11 份语料;`backend/tests/test_scene_3d_parity.py:44`(语料存在性断言)

**CI 与发布**
- `.github/workflows/tests.yml` — 唯一的测试门禁(`workflow_call`)
- `.github/workflows/ci.yml` / `release.yml` — 两个调用方
- `docs/RELEASING.md:11-14` — 版本号同步清单(5 处里只有 2 处有测试)
- `website/test/documentation-media.test.mjs:14 / :43` — 实际核对的那两处

**测试成本**
- `/private/tmp/.../scratchpad/pytest.log` — 本次全量:3756 passed / 391.67s / 最慢 45 条占 50.8%
- `backend/app/core/http_retry.py:19` + `backend/tests/test_llm_retry.py:144` — 串台的进程级重试次数
- `docs/PROCESS_STATE.md` — 16 条进程级状态,登记齐全但无重置纪律
