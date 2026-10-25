# ADR 0081 · 桌面级驱动（L3）与模型驱动网页（L2）：先立端口，再自研

- 状态：**Accepted（P0 / P1 / P2 已完成，P3 已实现待真机复核）** — 2026-10-24 定方向，2026-10-25 完成
  P0、macOS P1 与 P2，并实现 P3 的回放证据、清理与时间线卡片。维护者拍板：**L2 要做**（「任何网站上的任何事都能做」）、**回放要做且记全量**、**L3 倾向自研**
- 相关：[ADR 0075](0075-computer-use.md)（三层的边界与安全模型）、ADR 0044（确认卡）、
  ADR 0080（发布域的契约与判定原语 —— L2 确定性那一半）
- 代码位置：`electron/computerUse/ownWindowDriver.cjs`（L1）、`electron/computerUse/desktopDriverMac.cjs`（macOS L3）、`backend/app/domain/agent/computer_use.py` 与 `backend/mcp_server.py`（宿主桥客户端与工具层）、`backend/app/domain/agent/confirmable/computer_desktop.py`（桌面动作确认卡）

## 要解决什么

ADR 0075 只交付了 L1（应用自己的窗口）。剩下两层的缺口是**能力缺口**，不是体验缺口：

- **L2**：让模型在**任意网站**上做事。今天只有发布域那套确定性自动化（契约 + 判定 + 浮层），
  覆盖的是七个平台、四种形状；「没有契约的站点」目前完全无解。
- **L3**：操作**别的 App**（Finder、预览、系统弹窗、原生文件选择框）。发布域今天用 CDP 拦截
  「点了才创建的 file input」（`PageDriver.chooseFilesByClicking`），但**原生**弹窗没有这条路。

## 决定 1 · 先立端口，再谈实现

不管 L2 / L3 最后怎么实现，中间那层接口现在就该定下来，否则每加一种能力都要动确认卡与策略层：

```
DesktopDriver
  observe(target)  → { elements: ElementToken[], image?, meta }   // 观察:树 + 可选截图
  act(token|coord, action) → ActionResult                         // 动作:点 / 输入 / 滚动 / 按键
  verify(checkpoint) → { ok, reason, evidence }                   // 校验:按"用户的后置条件"判
  capabilities() → { tree, screenshots, input, platforms }        // 能力探测
```

- 端口放在 `electron/computerUse/ownWindowDriver.cjs`，**不认识任何具体平台**（不认识抖音、不认识 Finder）；
- 今天 L1 的实现包成 `OwnWindowDriver`（`capturePage` + `sendInputEvent`）—— 这一步是**纯重构**，
  行为不变、测试仍跑在现有守卫/overlay/cursor 上。`observe` 返回主窗口截图与空 `elements`（L1 没有可访问性树），
  `act` 只认 click / type / scroll，`verify` 明确 `verify_not_supported`，不冒充已验证；
- L2 / L3 各是这层端口的另两个实现（`BrowserDriver` / `DesktopDriver`），由开关决定挂不挂。

## 决定 2 · 感知：元素令牌优先，像素只做兜底

观察返回**可访问性树 / DOM 树**里的元素，每个元素一个**一次性令牌** `snapshot_id:index`：

- 动作只接受令牌或「观察时那一张的像素坐标」，**不接受"上一次观察"的旧坐标**；
- 令牌失效（页面/窗口变了）时动作**直接失败**并附带新快照，而不是"点了一下什么也没发生"；
- 像素路径必须绑定 `capture_id`：用哪张图算出的坐标，就用那张图授权，**一次性**。

理由来自发布域这两天的教训：**坐标会漂**（页面重排、多出一行提示），而"点了没反应"是最难查的失败。
可访问性树上的令牌把这类失败变成"令牌过期"，可判定、可重试。

## 决定 3 · L3 自研（维护者 2026-10-24 定）

外挂 [cua-driver](https://github.com/trycua/cua) 是可行路线（可访问性树 + 元素令牌 + 后台输入，
驱动本体 MIT），但它给不了我们最在意的东西：**它替我们决定了权限边界**，而我们的安全模型是
「白名单 + 每步确认 + 急停 + 可见性」。所以自研，把边界留在自己手里。

自研的最小面（**macOS 先行，Windows 第二，Linux 不做**）：

| 能力 | macOS | Windows |
| --- | --- | --- |
| 枚举窗口 / 前台窗口 | `CGWindowListCopyWindowInfo` | `EnumWindows` |
| 窗口截图 | `screencapture`（CGWindowListCreateImage；P1 实测路径） | `Windows.Graphics.Capture` |
| 可访问性树 | `AXUIElement`（`AXUIElementCopyAttributeValue`） | UI Automation |
| 输入注入 | `CGEvent`（鼠标 / 键盘） | `SendInput` |
| 权限 | **辅助功能** + **屏幕录制**（两项 TCC，都要先申请） | 无需 TCC |

**明确不在自研范围内**（写下来是为了不被"顺手"扩进去）：

- 后台注入到**不聚焦**的窗口：macOS 上做得到的只有"给某个 App 发事件但不动焦点"的窄路，
  先按"必须可见/可聚焦"实现，别承诺后台操作；
- 多显示器坐标系的复杂性：先按「主屏 + 单窗口居中」实现，多屏靠窗口几何换算；
- 不装 `cua-perception` 那类 AGPL 感知扩展（若要，另行评估许可）。

## 决定 4 · L2：模型驱动网页，与确定性自动化并存

- **入口同一套**：`computer_*` 家族工具，L2 的 driver 是 `BrowserDriver`（复用 `PageDriver` 的
  可信输入与 CDP，不新起浏览器）；
- **感知用同一套令牌**：DOM 元素 → `snapshot_id:index`，和 L3 的可访问性树同形 —— 上层模型不需要
  知道"这次是网页还是原生 App"；
- **和发布域的分工**：有契约的站点仍走契约（稳定、可测、不花钱）；没有契约、或契约没覆盖的步骤，
  才让模型上。二者**共用同一份超时、重试、失败归因**；
- **风险**：第三方站点有反自动化与风控，模型误点可能提交表单/发消息 —— 所以每一处「提交类」动作
  仍然是确认卡 + 可见性 + 急停，和 L1 一致。

## 决定 5 · 回放：元数据 + 截图 + 输入的字（维护者 2026-10-24）

与 ADR 0075 决定 5 同一条，L2 / L3 一并适用。实现要点：

- 记录点：**动作前后各一次**观察（截图 + 树摘要），动作本身、输入的字、判定结果；
- 存本地：数据目录下按会话分段，**不进团队同步**；删会话即删回放，另有「清空回放」；
- 受保护窗口（密码管理器、钥匙串、系统设置、终端）在 L3 里**截图打码、动作直接拒**；
- 时间线对用户可见（可展开看每一步），不做隐藏采集。

## 分阶段（每一阶段都能独立停）

| 阶段 | 内容 | 判定"做完了" |
| --- | --- | --- |
| P0 | `DesktopDriver` 端口 + `OwnWindowDriver`（把 L1 装进去） | ✅ 现有 CUA 测试全绿，行为零变化（2026-10-25） |
| P1 | L3 只读：窗口枚举 + 窗口截图 + 可访问性树快照（**不注入**） | ✅ Finder / 预览读树与截图、权限引导、MCP 工具接线通过（2026-10-25，macOS） |
| P2 | L3 动作：点击 / 输入 / 滚动（令牌 + 像素兜底） | ✅ Finder / TextEdit / Preview 三个真实 App 完成安全可逆动作；确认卡、过期绑定与受保护应用拒绝通过（2026-10-25，macOS） |
| P3 | 回放：时间线落盘 + 用户可见 | 🟡 动作前后证据、本机存储、时间线卡片与清空已实现并通过测试；桌面端重启后做真机 UI 复核 |
| P4 | L2：`BrowserDriver` + 模型驱动兜底 | 一个没有契约的站点完成一次填写（提交动作仍走确认卡） |

P1 的只读观察也需要对应权限；查询状态**不弹窗**，只有用户在原生引导里点了「向系统申请」才请求 TCC，
「打开系统设置」则由另一颗按钮显式触发，申请前讲清为什么要、可以随时撤销。

P1 实现注记：先按原表尝试了 `SCScreenshotManager.captureImage`，但在 macOS 27 的命令行工具里触发
`CGS_REQUIRE_INIT` 断言，`NSApplicationMain` / `RunLoop` 几种启动方式下又无法稳定返回；
因此 P1 的实际截图走系统 `screencapture`（同一 `CGWindowListCreateImage` 路径），尺寸用 `sips` 读取。
这不是静默降级：失败原样交回，且此处在 ADR 中留痕。后续若 SCK 命令行路径修好，可换回去。

2026-10-25 实测：`DesktopDriverMac` + Swift 工具已落地；Finder 与预览的窗口截图、AX 树均通过
（各返回 400 个元素）。`permissions` 只查询；`request-permission` 只在用户点击后调用；
`desktopPermissionGuide.cjs` 提供主进程原生引导，未授权时返回 `desktop_permission_required`。
宿主桥新增 `computer:desktop-{windows,screenshot,accessibility}`，MCP 对应新增
`computer_desktop_{windows,screenshot,accessibility}`；后端到 Finder 的联合冒烟通过。
桌面输入只经 `computer_desktop_{click,type,scroll}` 暴露，且每次先开确认卡；AX 元素令牌只用于该次动作。

P2 动作边界：每个动作只接受**一次性**绑定 —— AX 元素令牌，或绑定一次截图的像素坐标。
令牌按 AX 路径重读并比对角色 / 标题 / 窗口几何；截图绑定在动作前复核窗口位置与尺寸。
二者一旦开始执行就作废，失败也不能拿旧坐标重试。密码管理器、系统设置、终端等受保护应用直接拒绝；
动作前聚焦目标 App，并在发出 CGEvent 前确认点击点所在的最上层窗口确实属于它（菜单栏单独放行）；
沿用确认卡、急停、全屏红框与指针提示。
2026-10-25 真机冒烟：Finder 菜单点击、TextEdit 输入与滚动、Preview 滚动均通过；临时文档和进程已清理。

P3 实现：桌面动作的确认执行在前后各截一张缩小证据，写入
`<数据目录>/agent-replay/<session>/<confirmation>/`；消息里只存 action、目标、尺寸和受保护 URL。
工具时间线展开后显示前后图、动作摘要和「清空本会话回放」。清空会删目录并从消息/确认卡去掉
replay 元数据；删会话同时删目录。受保护应用的只读截图在交给模型前替换为打码占位，不下发真实像素。

## 后果

- 端口一旦立起来，L2 / L3 是"加一个 driver"，而不是"改一遍策略层"；
- 自研的代价是显式的：两项 macOS 权限、两套平台 API、多屏与后台注入的边界要自己扛 ——
  换来的是权限模型完全按我们的规矩来；
- L2 与确定性自动化并存，短期会有"两条路"的复杂度，但它们的**判定与取证是同一套**，
  不会出现"模型点的失败了没法查"；
- 回放记全量会把本地存储推上去（截图占大头），需要配合"按会话保留 N 天"的清理策略 ——
  具体天数等 P3 定，先按"删会话即删"起步。
