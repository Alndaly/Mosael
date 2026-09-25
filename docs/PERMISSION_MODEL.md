# 资源与权限:现状盘点

> 这份是**盘点**,不是设计。每一条都对着代码核过,能跑的都跑过 —— 结论后面括号里是复现方式。
> 目的是把「什么东西属于谁、谁能动它」摆平在一页里,再判断哪些地方对不上。
>
> 结论先行：最初盘点发现的实例管理员推断和共享供应商凭据已经修复。部署级配置由
> `User.is_deployment_admin` 守卫；供应商连接、凭据、模型和默认选择归用户。下面保留问题的来历，
> 同时标出当前状态，避免旧结论继续指导新代码。

## 1. 资源挂在哪一层

按**有效归属**（含父表归属，不只看本表有没有某个列）分类：

| 层 | 有哪些 |
| --- | --- | --- |
| **工作区级** | 素材、序列、片段、项目、工作流、智能体记忆、确认卡、用量事件、通知、字体、LUT、声音… |
| **放在工作区里、但归人** | 发布账号、浏览器池档案、智能体会话、生成会话、定时任务 —— `owner_user_id` 说是谁的,`resource_shares` 说主人把它共享进了哪个工作区(见 `domain/sharing`) |
| **用户级** | 登录会话、第三方身份、供应商连接与凭据、连接下的模型、每项能力的默认模型 |
| **实例级** | 网络配置、TTS/ASR 运行时配置、插件包与启用状态、部署管理员身份等 |

两点值得先注意:

- **供应商连接归人。** `ProviderProfile.owner_user_id` 决定端点和非密配置属于谁；
  `ProviderCredential` 用 `(profile_id, owner_user_id)` 保存同一人的 API Key、OAuth 与密字段。
- **读取只返回已解析连接。** `ResolvedConnection` 是稳定连接 + 动态秘密的运行时快照；
  `resolve_connection` / `require_connection` 按 owner 过滤，不跨用户找“第一条能用的”。

## 2. 当前闸门

| 闸门 | 唯一判据 | 用途 |
| --- | --- | --- |
| `ensure_workspace_access` | 是工作区成员 | 只读入口;非成员统一 404 |
| `ensure_workspace_member` | 是工作区成员 | 语义上只读、但传输层使用 POST 的检索入口 |
| `ensure_workspace_perm` | 操作名映射到最低角色 | 写入入口,调用点必须显式点名操作 |
| `ensure_workspace_role` | 角色不低于指定档 | 成员管理等明确需要 admin / owner 的入口 |
| `ensure_deployment_admin` | `User.is_deployment_admin` | 网络、插件、解释器和模型下载等整个部署的配置 |
| `require_asset` / `require_sequence_access` | 资源存在 + 上述读/写闸门 | 资源定位与授权收在同一领域入口 |
| `require_worker_key` | 数据目录下的进程密钥 | 本机卫星进程的 claim / report / heartbeat |
| 确认卡 | 工具 manifest 的 `confirmation` + 会话规则 | 智能体对不可逆或对外动作的用户授权 |
| `sharing.ensure_usable` | 是主人,或主人把它共享进了它所在的工作区 | **用**私有身份的那一刻:发布账号(`publish.start_publish`)、浏览器池档案(`browser.open_session` / `attach_session` / `usable_profile`)。`actor` 必填,None 被拒 |
| 运行的授权(`domain/authority`) | 跑的人过得了闸,**且**被执行的每一版图(含子流程那一版)有一个担保人(作者或认可过它的人)也过得了 | 工作流节点调上面两道闸时,`actor=` 传 `workflows.authority.current_authority(db)`,不是 `current_actor`。见 §3.8 |
| `host_files.ensure_readable` | 是部署管理员,或路径(realpath 之后)落在管理员共享给成员的本机文件夹里 | **读一个用户给出的本机路径**的那一刻:工作流 `browser_upload` 的 `file_path`、智能体浏览器 upload 动作、按本机路径导入素材。放行得到 `HostFile`,`browser.upload_file` 只收它。`actor` 必填,None 被拒 |
| `host_files.ensure_whole_machine` | 是部署管理员 | 在这台电脑上**不隔离地跑代码**:`run_host_code`、`blender_execute` 确认卡(批准的人) |

工作区只使用 `owner > admin > editor > viewer` 四级角色。`ensure_workspace_perm`
保留操作名是为了让调用点可读,而不是恢复可逐位覆盖的权限矩阵。

## 3. 已修复的历史问题

### 3.1 实例管理员曾可自助获得 — ✅ 已修复

它的实现是「遍历此人的所有成员身份,任意一处 role ≥ admin 且持有该权限 → 放行」。而**任何登录
用户都可以新建工作区,并在自己新建的工作区里是 owner**。

复现:

```
viewer(只在别人的工作区里是 viewer)改实例级网络设置  -> 403
他自己新建一个工作区之后,再改一次                    -> 200
```

当前 `ensure_deployment_admin` 只读取 `users.is_deployment_admin`；首个引导账号获得该事实，创建工作区
不会改变它。网络代理、插件启用、解释器路径和模型下载继续属于部署级设置。

### 3.2 供应商凭据曾可跨用户读取 — ✅ 已修复

旧实现的 `POST /agent/provider-credentials/{id}/acquire` 只要登录身份，并可能返回共享档案的明文
OAuth 凭据。当前连接与凭据都归用户：设置列表按 `ProviderProfile.owner_user_id` 过滤；acquire / commit /
release 同时验证连接 owner，并按 `(profile_id, current_user)` 读写。别人的连接统一表现为 404。

旧复现记录：

```
viewer 取供应商凭据 -> 200
响应里含明文 access token 吗:True
```

旧问题的根因不是少加一个 `ai` 权限检查，而是凭据没有 owner。现在由资源归属解决：即使知道 id，
也无法读取、刷新或给别人的连接写入自己的凭据。

### 3.3 写权限曾从 HTTP 方法推断 — ✅ 已修复

`ensure_workspace_access` 现在是纯只读闸门,不读 ASGI ContextVar。所有写入入口显式
调用 `ensure_workspace_perm`;非 HTTP 路径复用同一领域 Interface 时也不会默认放行。
`tests/test_write_permission_is_explicit.py` 防止新写入路由回到隐式推断。

### 3.4 逐权限覆盖曾与角色重叠 — ✅ 已修复

可编辑权限矩阵已删除,工作区只保留四级角色。供应商凭据不属于工作区权限,
而是由 Provider Profile 与 Provider Credential 的 owner 决定。

### 3.5 `code` 节点曾靠特权角色止血 — ✅ 已修复

`code` 现在是普通工作流内容,执行收口在 `app/domain/sandbox`。沙箱默认无网、
不继承后端环境,并在没有隔离后端时 fail closed。旧的 `ensure_graph_node_privileges`
和 `PRIVILEGED_NODE_TYPES` 已删除。

### 3.6 私有账号 / 档案曾可被同事拿去用 — ✅ 已修复

`sharing.may_use` 早就写好,但只挡住了列表:工作流发布节点、`browser_open` 池模式、`POST /publish/tasks`、
智能体的发布与池档案确认卡、定时任务和 webhook 触发的运行,全都只查「是不是这个工作区的人」。同事猜到 id,
或在工作流里填上别人的账号 id,就能拿别人的平台登录态发帖、在别人已登录的浏览器里取 cookie。

现在**私有的发布账号和浏览器池档案只有主人和被共享到的人能用**,在用的那一刻查,且只在一处:

- `publish.start_publish(…, actor=…)` —— 发布页、工作流发布节点、智能体 `publish_asset` 卡都经过它;
- `browser.open_session(…, actor=…)` / `browser.usable_profile(…, actor=…)` —— 工作流 `browser_open` 池模式、
  智能体 `browser_pool_open` 卡、从链接导入借 cookie(探测与下载);
- `browser.attach_session(…, actor=…)` —— 接着用一个开着的池档案会话(工作流下游浏览器节点、智能体内联动作):
  拿到会话 id 不等于有权用那个登录身份。

`actor` 是**必填**关键字参数,没有默认值;传 None 一律拒绝。谁是 actor:

| 入口 | actor |
| --- | --- |
| HTTP 路由 | 当前登录用户 |
| 手动运行的工作流 | 点运行的人(`Job.created_by`,节点里经 `jobs.current_actor` 取) |
| 定时任务 / webhook 触发的运行 | **任务主人**(`ScheduledTask.owner_user_id`,见 `scheduler.operations._open_run`)—— 与它用谁的钥匙、记谁的额度是同一条归属 |
| 子流程 | 父运行的 actor |
| 智能体确认卡 | 批准这张卡的人(`ToolConfirmation.decided_by`;自动放行记在会话主人头上) |
| 发布执行器(桌面端 worker) | 不重查 —— 认领的是建任务时已经过闸的任务 |

拒绝是 `sharing.NotUsableError`(文案 key `shareErr_notUsable_*`,中英两份),HTTP 回 403,工作流与确认卡
把 key 原样记进失败原因。工作流字段下拉(`publish_accounts` / `browser_profiles`)、发布页账号列表、浏览器池
列表用同一个判据(`sharing.usable_filter`)—— 列出来的,选了就用得上。

老数据不做兼容:已经存在的工作流 / 定时任务如果引用了 actor 用不了的账号或档案,下一次运行会带着这句话失败,
由主人共享出来,或改用自己的。棘轮:`tests/test_private_identities_need_their_owner.py`。

### 3.7 本机文件曾对所有成员开放 — ✅ 已修复

后端跑在某一台电脑上。工作流 `browser_upload` 的 `file_path` 收这台电脑上的任意路径;智能体浏览器的
`/agent-browser/act` 把 upload 动作的 args 原样交给执行器;`navigate` 接受 `file://`;「本机执行代码」与
Blender 代码卡谁批准都跑。单机用时这台电脑就是用户自己的,没问题;同事经团队部署或远程访问进来之后,
填一个 `~/.ssh/id_rsa`,主人的私钥就被塞进了任意网页。

现在**这台电脑上的文件是部署主人的私有资源**,读的那一刻查,且只在一处(`domain/host_files`):

- 部署管理员(`User.is_deployment_admin`)整台机器都可以 —— 单机用时唯一的用户就是管理员,零摩擦;
- 其他人只有两种:素材库里的文件(`host_files.asset_file`,调用方先按工作区校验素材),或落在管理员
  **共享给成员的本机文件夹**(部署级设置 `DeploymentConfig.shared_host_folders`,管理控制台里改,
  `ensure_deployment_admin`)里的路径。判断前一律 realpath —— 共享文件夹里的软链接、`..` 借不了道;
- 没权限的人拿到的是 403(`hostErr_notReadable`),**不存在也是 403**:探不出别人机器上有什么;
- 浏览器 `upload` 只能经 `browser.upload_file(…, HostFile)`,`run_action` 直接拒 upload;导航只认 http(s)。

| 入口 | actor |
| --- | --- |
| `POST /assets/import-local`、`POST /agent-browser/act`(upload) | 当前登录用户 |
| 工作流 `browser_upload` | 这次运行的 actor(与 §3.6 同一条) |
| `run_host_code` / `blender_execute` 确认卡 | 批准这张卡的人 |

棘轮:`tests/test_host_files_belong_to_the_deployment_owner.py`(seam 的 `actor` 必填、调用点不写 None、
`HostFile` 只在 host_files 里构造、每个已知入口都过闸)。插件以用户身份运行、能读它读得到的一切 ——
它们由部署管理员安装,不在这道闸里。

### 3.8 同事改了图,主人的任务就替他用主人的东西 — ✅ 已修复

§3.6 挡住的是「以自己的身份用别人的」。可工作流是工作区内容、同事能改,而定时任务 / webhook 替**任务主人**跑:
同事改了主人的图,到点一跑,那次运行就以主人的授权用主人的私有账号 / 档案 / 本机文件 —— 借别人的任务用别人的东西。

现在一次运行的授权是两半的**交集**(`domain/authority`):

- **跑的人**:和以前一样(路由是当前用户,手动运行是点运行的人,定时任务 / webhook 是任务主人);
- **被执行的每一版图的担保人**:保存这一版的人(`WorkflowRevision.created_by`),加上事后「认可这一版」的人
  (`workflow_revision_attestations`)。`workflows.authority.current_authority` 沿 job 父链往上收:
  `call_workflow` 调起的子流程是一条子 job,它自己那一版也要有担保人。每一版都得有**至少一个**担保人
  自己也过得了闸。

作者因此必须记全:`create_workflow` / `update_workflow` / `edit_workflow_graph` / `commit_graph_revision` /
`create_initial_revision` / `restore_workflow_revision` 的 `created_by` 必填、没有默认值。画布保存、导入、官方
模板记点按钮的人;智能体改图记批准那张卡的人(自动放行记在会话主人头上);恢复旧版记恢复的人。老修订由迁移
`backfill-workflow-revision-authors` 补上:这条工作流最早一版有记录的作者,都没有时是工作区 owner。

挡下来时报 `shareErr_notVouched_*` / `hostErr_notVouched`(中英两份),说是哪条工作流的哪一版,失败现场带
`details.attest = {workflow_id, workflow_name, revision}`。工作流运行历史与定时任务的运行记录据此给「认可这一版」
(`POST /workflows/{id}/revisions/{n}/attest`);版本历史里当前版是别人存的、自己还没认可时也给。认可**不改图、
不增版**(修订不可变、执行语义相同不增版),只多记一个担保人;谁都能点,但只对点的人**自己用得了**的东西有用。

单机用时跑的人、作者、担保人永远是同一个人,零摩擦。棘轮:`tests/test_runs_act_with_the_revision_authors_authority.py`
(`created_by` 必填且调用点不写 None;执行器里调闸门的 `actor=` 不是 `current_actor(...)`)。

## 4. 已经对上的地方

盘点不能只列问题,否则读的人会以为整套都在漏:

- **工作区边界是严的**:不是成员一律 404(不泄露存在性),35 张表全部按 `workspace_id` 过滤。
- **不可逆动作有专门的一档**:`external`(公开发布 / 对外写请求 / 本机跑代码),措辞和徽标都不同,
  三档权限模式下 auto 也不放行它 —— 要么规则命中,要么隔离判断者点头。
- **代码执行 fail closed**:`code` 节点只能通过隔离执行器运行,无沙箱时不回落。
- **凭据本身有周期**:`AuthSession` 现在会过期、会自清,服务令牌 30 分钟。
- **worker 通道不走用户身份**:本机 worker 用启动时下发的进程密钥,网页读不到那个文件。

## 5. 剩余差距

- 默认仍是本地单用户部署;远程多用户部署的全部路径需继续用隔离测试验证。
- `credentials` 这个词仍同时出现在 Provider Credential 和插件凭据中;它们的归属已分开,
  但 UI 文案和新文档必须继续明确区分「我的 AI 连接」与「工作区插件秘密」。
- 发布账号 / 浏览器池档案的**管理**(改名、停用、复检、删除)仍只查工作区角色,没有按归属收紧:
  §3.6 管的是「用」。同事看不到别人的私有账号,但猜到 id 仍能改它、删它 —— 是否只许主人管理,另行决定。
- worker key 证明的是卫星进程,不是最终用户;将 external job 放到其他机器前,
  需单独解决该部署的密钥下发与信任范围。

## 6. 这份文档怎么核对

结论都来自可复现的检查,不是通读印象:

- 表的作用域:对 `models.py` 做 AST 扫描,按有没有 `workspace_id` / `user_id` 分类。
- 路由闸门:对 `app/api/routes/*.py` 做 AST 扫描,收集每个路由函数体(含一层本地辅助函数)里
  调用到的 `ensure_*` / `require_*`。**先用正则做过一遍,结论是错的** —— 正则在第一个空行处截断
  函数体,把一批有闸门的路由报成没有。
- §3.1、§3.2 的结论各有一次实跑,输出原样抄在上面。
