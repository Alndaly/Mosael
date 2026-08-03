# Open Studio — 前端彻底重做 + 编辑内核补全(第一版)设计

日期:2026-07-15
状态:已与用户对齐(视觉方向、痛点、交付边界均经确认)
上位计划:前身项目的重写实施计划(已归档)

## 1. 背景与问题

当时后端已有真实关系模型与 domain 骨架,但前端只是 260 行的脚手架:

- 视觉是未加工的 shadcn 默认样式,无设计语言。
- 导航仅 4 项,缺计划 §15.1 规定的 8 栏信息架构。
- 编辑器是假的:监视器为静态图标,时间线为只读 div,无任何编辑交互。
- 布局密度、比例、空间使用不符合专业创作工具标准。

用户确认四个痛点全部成立,要求彻底重做。

## 2. 已确认的方向

- **视觉**:浅色专业工具(计划 §15.2),执行工艺对标 Linear/Notion/Raycast。冷灰背景、白面板、蓝主色、无营销渐变、无装饰光效;深浅两套主题都单独校准。
- **第一版交付重心**:设计系统 + 8 栏外壳 + 真实编辑器。其余板块(首页/素材库/批量/发布/知识库/设置)用高质量占位页;AI Studio、Scheduler、Plugins 保留现有功能、重新套入新设计系统。
- **流程**:每个任务完成即 commit;持续推进直至完成。

## 3. 设计系统

`frontend/src/design/tokens.css` 重写:

- **排版**:UI 用 Inter/system 栈;字号刻度 11/12/13/14/16/20/24;时间码与数值用 `ui-monospace` + `tabular-nums`。
- **间距**:4px 基准网格;控件高度 sm=28 / md=32;整体密度紧凑。
- **颜色**:中性冷灰背景、纯白面板、精炼蓝主色;新增语义轨道色 token(video/audio/subtitle/overlay 四组,各含 bg/border/text),浅深主题各自校准。
- **层级**:1px 边框 + 背景明度差 + 极轻阴影;禁止厚重装饰。
- 保留 shadcn 变量映射,现有组件继续可用;button/badge/card 按新刻度微调,新增 tooltip(图标导航必需,计划 §15.2)。

## 4. 信息架构与外壳

- 左侧 56px 图标导航栏(tooltip 显示名称):首页 / 素材 / 剪辑 / AI Studio / 批量 / 发布 / 知识库 / 设置。
- 顶栏:工作区·项目标识与创建入口、主题/语言切换(设置页内亦有完整偏好控制)。
- `main.tsx` 拆分:`components/layout/AppShell.tsx`、`features/*` 每板块一个 view 文件;业务文件 ≤ 250 行。
- 占位页统一模式:标题 + 一句定位描述 + 精致空状态(图标、说明、指向计划中未来能力),全部走 i18n,深浅主题可用。

## 5. 真实编辑器(旗舰)

四区布局:左素材池 / 中监视器 / 右检视器 / 底部通栏时间线。

- **时间线**:时间码标尺(自适应刻度)、可点击/拖动播放头、缩放(px/秒,Cmd+滚轮 + 按钮)、多轨渲染(按 track.kind 着色)、片段拖拽移动、两端裁切手柄、吸附(相邻 clip 边缘、播放头、0 点)、单选、Delete 删除、Space 播放暂停。
- **几何纯函数** `domain/timeline/geometry.ts`:time↔px、标尺刻度计算、吸附解析、trim 钳制、同轨重叠检测。Vitest 单测(计划 §24.3)。
- **状态分层**(计划 §14.2):React Query 管服务端 sequence;Zustand 只存拖拽草稿(dragDraft)与瞬态 UI(选择、播放头、缩放);松手才提交 operation,失败回滚刷新。
- **监视器**:真实 `<video>`,播放头落在视频轨某 clip 内时播放对应 asset 区段(MVP 为单视频轨顺序预览);显示时间码;播放中播放头跟随。
- **素材池**:真实导入(multipart)、缩略图、名称/时长/类型,点击加入时间线末尾,拖拽到时间线指定位置。
- **检视器**:选中 clip 显示 asset、时间范围、时长、速度/增益(只读展示 MVP);未选中显示 sequence 规格。

## 6. 后端补全(本次范围)

编辑内核操作(计划 §10),每个都校验不变量、写 `sequence_operations` + `sequence_revisions`、递增 revision:

- `move_clip(clip_id, track_id?, timeline_start)` — 校验非负、目标轨存在且 kind 兼容。
- `trim_clip(clip_id, timeline_start, src_in, src_out)` — 校验 src_out > src_in、时长非负。
- `delete_clip(clip_id)`。

路由:`PATCH /api/sequences/{id}/clips/{clip_id}/move`、`.../trim`、`DELETE .../clips/{clip_id}`,全部返回完整 SequenceOut。

媒体服务:

- `GET /api/assets/{asset_id}/file` — FileResponse(Starlette 原生支持 Range),供监视器播放。
- 导入时用 ffmpeg 生成缩略图(best-effort,失败不阻塞导入),`GET /api/assets/{asset_id}/thumbnail` 提供。

pytest 覆盖三个新 operation 的成功与非法输入;导出 openapi.json 并重新生成前端 schema(计划 §14.1:禁手写后端类型)。

## 7. 测试与验收

- 后端:move/trim/delete 单测 + 既有测试全绿。
- 前端:geometry 纯函数 Vitest 全绿;`tsc --noEmit` + build 通过。
- 端到端(浏览器实测):创建工作区→项目→导入视频→建时间线→拖入两段素材→移动/裁切/删除→播放头拖动→监视器播放→刷新后状态恢复。
- 视觉:8 栏可达,深浅主题、中英文全覆盖,无文本溢出。

## 8. 非目标(本次不做)

完整 AI Studio 外壳、生成 provider 接通、渲染导出管线、转写视图、撤销/重做 UI(operation 记录已为其铺路)、多选与波纹编辑、音频波形、Windows 打包验证。
