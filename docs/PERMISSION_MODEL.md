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
| **工作区级** | 素材、序列、片段、项目、工作流、发布账号、浏览器档案、定时任务、智能体会话与记忆、确认卡、用量事件、通知、字体、LUT、声音… |
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
- worker key 证明的是卫星进程,不是最终用户;将 external job 放到其他机器前,
  需单独解决该部署的密钥下发与信任范围。

## 6. 这份文档怎么核对

结论都来自可复现的检查,不是通读印象:

- 表的作用域:对 `models.py` 做 AST 扫描,按有没有 `workspace_id` / `user_id` 分类。
- 路由闸门:对 `app/api/routes/*.py` 做 AST 扫描,收集每个路由函数体(含一层本地辅助函数)里
  调用到的 `ensure_*` / `require_*`。**先用正则做过一遍,结论是错的** —— 正则在第一个空行处截断
  函数体,把一批有闸门的路由报成没有。
- §3.1、§3.2 的结论各有一次实跑,输出原样抄在上面。
