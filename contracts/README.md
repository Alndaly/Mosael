# 契约(contracts/)

这里放**必须在多个实现之间字面一致的语义**,以语言中立的语料形式表达,由各侧的测试套件分别执行。

不是文档,是可执行的规约:任何一侧改了语义而其它侧没跟上,**所有侧的 CI 都会红**。

## 为什么需要它

有些语义天生只能有一份定义,却必然有多份实现。

### `scene-cases.json` —— 场景契约

「t 时刻画面上有哪些层、什么 z 序、谁是 base、画面播多久。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/playback/sceneModel.ts` | `sceneModel.parity.test.ts` |
| 导出 | `backend/app/media/scene.py` | `backend/tests/test_scene_parity.py` |

**为什么不共用一份实现**:预览要在浏览器里本地同步跑到 60fps,还要处理尚未提交到后端的拖拽草稿;
导出要无头、在后端、并且可以被外部 worker 认领跑在别的机器上(见 [ADR-0002](../docs/adr/0002-claim-report-worker-protocol.md))。
这两个约束各自成立,合起来决定了模型必然存在于两种语言里。**"只有一份实现"不是可选项**,所以一致性
只能靠契约。

**这是有代价换来的教训**。契约诞生之前两侧各自手写、各自有绿测试、语义却相反,产生了用户可见的成片不一致:

- **上层 video 轨静音** —— 预览显示画面,导出把整层丢掉。给画中画轨点一下静音,成片里那层画面就没了。
  (轨道头是**喇叭**图标,语义只关音频,所以预览是对的。)
- **最底 video 轨为空** —— 预览把上层片段当 overlay(cover 取景),导出把它提为 base(遵 fill_mode)。
  同一条时间线两种取景。

两个 bug 都不是谁写错了代码,是**两份实现各自自洽而互不相识**。

### `subtitle-cases.json` —— 字幕契约

「同一份 `subtitle_style` 在同一画幅下,字幕框解析出来的几何与用色是什么、这个框放在画面的哪个像素上。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 预览 | `frontend/src/features/editor/subtitleStyle.ts` | `subtitleStyle.parity.test.ts` |
| 导出 | `backend/app/media/text_render.py` + `render_executor._subtitle_overlay_pos` | `backend/tests/test_subtitle_parity.py` |

**为什么不共用一份实现**:同上 —— 预览要跟着显示尺寸缩放(字号用 `cqw`、定位用百分比,交给浏览器解析),
导出要在原生帧上无头渲染(px 与 overlay 坐标)。两种写法**在画幅原生宽度上解析到同一个像素值**,
所以语料记的是**解析后的结果**,不是 CSS 写法。

**建立契约之前它是这样的**:圆角 `0.33em`、内边距 `0.16em 0.55em`、行高 `1.45`、最大宽 `86%`、投影 ——
这六组数字在 `Monitor.tsx` 的 `className` 里和 `_subtitle_style_css` 里各手写一遍;竖直定位也是两份,
后端那份的注释就写着「镜像预览 subtitleCss」。**"靠注释提醒对方"不是机制。** 建立契约时两侧恰好还是
一致的,所以这次没有换来 bug —— 它防的是下一次。

### `context-meter-cases.json` —— 上下文水位契约

「一组 pi 消息占了多少 token。」

| 实现 | 位置 | 测试 |
| --- | --- | --- |
| 决定压不压 | `agent-sidecar/src/compaction.ts` | `test/context-meter.parity.test.mjs` |
| 显示还能聊多久 | `backend/app/domain/context_meter.py` | `backend/tests/test_context_meter_parity.py` |

**为什么不共用一份实现**:压缩发生在 Node 侧的 pi 循环里,展示发生在 Python 侧的 HTTP 响应里,
中间隔着一次进程边界;而水位要在「还没开口」时就能看(打开旧会话、刚换模型、上一轮失败),
那些时刻根本没有新的一轮可以回报。

**建立契约时它已经坏了**。`context_meter.py` 的模块注释写着「两份实现必须保持同一套锚点规则,
改一处就要改另一处」—— 而它没做到:后端补上了 `cacheRead`(缓存命中的部分照样占窗口),
sidecar 那份没跟上。开着 prompt caching 时 `input` 只剩新增的一小段、绝大部分记在 `cacheRead` 上,
于是 sidecar 看到的水位只有真实值的零头:**界面显示 90%,压缩迟迟不触发,直到某一轮直接超窗失败**。
契约还顺带抓出第二处:Python 的 `json.dumps` 默认在冒号后加空格、JS 的 `JSON.stringify` 不加,
每个工具入参都系统性差出几个字符。**靠注释提醒对方不是机制。**

## 改语义的正确顺序

1. **先改 `contracts/*.json`**
2. 跑两侧测试,**看着它们一起红**
3. 再改两侧实现,直到一起绿

反过来做——先改实现、再补语料——就把语料降级成了实现的复读机,它将不再能防住任何东西。

## 什么该进契约,什么不该

**该进**:多个实现必须逐字一致、且不一致会被用户看见的语义。

**不该进**:只有一份实现的东西(直接单测就好);以及**刻意允许两侧不同**的东西——
典型是**调色**:导出走 ffmpeg 的 `eq`/`curves`/`lut3d`,预览是 CSS/canvas 近似。
这是有意的取舍而非缺陷(见 `frontend/src/features/editor/monitorFilters.ts` 的说明与
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) 的「预览与导出」一节),把它写进契约只会逼两边
互相迁就到都变差。
