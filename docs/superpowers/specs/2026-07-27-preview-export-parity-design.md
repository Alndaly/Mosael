# 预览 = 导出:渲染一致性(治本)— 设计

日期: 2026-07-27
状态: 进行中 —— **P1 完成**(合成器修黑闪);**P2 落地但未接线**(导出代理 + 离线渲染核心已建、
待 P3 编码管线驱动后才能逐像素校验);**翻默认预览暂缓**(留待 P2/P3 验证充分);P3–P4 待做。
关联: [WebCodecs 预览合成器设计](2026-07-19-webcodecs-compositor-design.md)(本设计的地基:S0–S2 已落地的 `CanvasCompositor`)

## 问题

预览与导出是**两套独立的画面渲染实现**,语义靠人工对齐,必然漂移:

- 预览:前端。默认仍是 DOM 元素叠层(`Monitor.tsx`);灰度中的 `CanvasCompositor`(canvas 2D,读 720p 代理)。
- 导出:后端 ffmpeg 滤镜图(`render_plan.py` + `render_executor.py`,读原片)。

已暴露的 parity bug(逐个补都治标):底轨比上层短 → 导出画面截断(已修);画中画多轨定位/层级;段落切换一瞬黑屏;……

**治本 = 画面合成只有一套实现,预览与导出都由它产出。** 编码分歧只留在"谁来编码"——已定 **方案 Y:canvas 合成 → ffmpeg 只编码/混音/封装**。

## 核心难点:代理 vs 原片(必须先解决)

`CanvasCompositor` 现在**只解码 720p H.264 代理**——这是有意的(规避 webm/hevc/奇怪封装的解码风险)。但**导出要全分辨率原片**。所以"canvas 合成导出帧"必须回答:全分辨率的源帧从哪来?

三条路,本设计选 **C**:

- A. 导出也用代理 → 画质只有 720p。**否决**(导出必须原生分辨率)。
- B. canvas 用 WebCodecs 解码原片 → 撞上代理当初要规避的解码风险(webm/hevc 解不了)。**否决为默认**,仅作"源恰好是良好 avc mp4"时的快路。
- **C(选)。导出专用「全分辨率代理」:ffmpeg 把每个用到的源转成短 GOP、全分辨率 H.264 mp4(faststart),canvas 只解码它。** 与预览代理同一套管线,只是分辨率=原生。解码输入永远是已知良好的 avc mp4,canvas 合成逻辑不变;ffmpeg 只在"造导出代理"和"最终编码"两端出现,**中间的合成完全是 canvas 一套**。
  - 代价:导出前要为未缓存的源转一份全分辨率代理(一次性、可缓存复用)。可与预览代理共用缓存策略。

> 结论:合成单源(canvas),ffmpeg 只做「造可解码源」+「编码封装」两端,不碰任何叠加/定位/调色/字幕。parity 从根上消失。

## 目标架构(方案 Y + 路 C)

```
时间线 ──► 场景模型(纯数据:每帧的层列表 = 源/src时间/transform/opacity/grade/z序/文本)
                     │
        ┌────────────┴─────────────┐
     预览渲染                     导出渲染(离线,确定性)
   CanvasCompositor            同一 CanvasCompositor.draw(model, t)
   (rAF, 720p 代理)            (逐帧 seek 全分辨率代理 → 合成帧)
                                        │
                                 帧 → ffmpeg(仅编码 + OfflineAudioContext 混音 + 封装)
```

- **一个场景模型 + 一个合成器 `draw(model, t)`**(只画视频/图片层)。预览是它的实时循环;导出是它的离线逐帧循环。二者共用**同一份绘制代码**,画面天生一致。

### 文字层不进 canvas(P0 调整,降风险)

调研发现文字**已经一致**,不必上 canvas:预览的字幕/花字是 DOM 叠层(读 `subtitleCss` 行内样式);
导出侧 `text_render.TextRasterizer` **用 app 同一份 CSS(headless chromium + @font-face)渲成 PNG** 再由
ffmpeg 烧录——两边同源 CSS,早已逐像素对齐。所以:

- **canvas 只负责视频/图片合成**(parity bug 都在这层);
- **文字仍是独立层**:预览 DOM(CSS)、导出 ffmpeg 烧 CSS→PNG。方案 Y 里,ffmpeg 把文字 PNG 叠在
  「canvas 已合成好的视频帧」之上再编码。文字排版一致性沿用现成机制,**不在 canvas 上重造 CSS 文本布局**(高风险活直接免掉)。

## 分阶段(每阶段带 flag、ffmpeg 老路作 fallback、独立可验)

- ~~P0 字幕/花字上 canvas~~ **免掉**:文字已 CSS 同源一致(见上),canvas 只做视频/图片;文字由 ffmpeg 烧 CSS→PNG,叠在 canvas 帧之上。
- **P1 修视频合成 bug ✅(翻默认暂缓)。** 段落切换黑闪已治本:合成器预热即将播放片段的解码器(`prewarmLayers`,冷片段在到达前完成 fetch/解析/首帧),不再黑闪(`CanvasCompositor` + `Monitor`)。画中画多轨已核对与 `MonitorElement` 逐项一致,翻默认不会走样。**翻默认(compositor flag 默认开)拆出,待 P2/P3 真机验证充分后再做**——它改真实预览引擎(含音频时钟切到 WebAudioMixer),值得拿真实工程先验。验证方式:真机多轨 PiP / 相邻片段切换 / 底轨短于上层。
- **P2 离线渲染核心 + 导出代理(路 C)——已落地,未接线。**
  - ①后端 ✅:`ensure_export_proxy` 惰性造全分辨率短 GOP H.264(crf16 近无损)导出代理,`export-proxy.mp4` 缓存复用;`GET /assets/{id}/export-proxy` 服务(复用预览代理管线,`build_proxy(max_height=None)`)。测试覆盖原生分辨率保留 + 建/服务/缓存。
  - ②前端权威 ✅:`sceneModel.sceneLayersAt`(唯一「t 时刻可见层」,8 单测)+ `scenePaint.paintScene`(唯一绘制代码,合成器已改调);预览与导出从此共用「画什么/怎么画」。
  - ③前端离线核心 ✅(未接线):`OfflineVideoSource`(可 await 的整-GOP 确定性解码)+ `OfflineFrameRenderer.renderFrameAt(t)`(精确 seek 导出代理 → paintScene 到 OffscreenCanvas)。
  - **未闭环**:renderFrameAt 尚未被导出流程调用,依赖 WebCodecs + 后端已建代理,故「离线帧 == 预览同 t 帧(pixel diff)」的验证要等 P3 编码管线接上、真机跑。已知取舍:色阶曲线 LUT 在 OffscreenCanvas 上 url(#) 不解析,当前仅应用可用 CSS 表达的调色(设计既定非目标)。
- **P3 编码管线(方案 Y)。** 离线帧逐帧 → 后端 ffmpeg(rawvideo 管道)编码;音频用 `OfflineAudioContext` 渲整段混音(gain/duck/fade/solo)→ 交 ffmpeg;进度 + 取消。验证:整条时间线导出成片,画面与预览一致、音画同步。
- **P4 导出切新路,ffmpeg render_plan 老路留 fallback(flag)。** 新路稳定后默认;WebCodecs 不可用 / 造代理失败 → 回退老 render_plan。逐像素回归:同一时间线两路各导一版,采样帧 pixel diff 入 CI。

## 非目标 / 风险 / 缓解

- **非目标**:WebGL 精确 LUT(canvas 2D `ctx.filter` 先顶,与现预览同精度);改动导入流程(导出代理是导出时惰性造,不进导入)。
- **风险**:①字幕上 canvas 的排版与现 DOM 完全一致(字体度量/换行/描边);②离线 seek 的帧对齐(短 GOP 代理保证);③帧从渲染层传给 ffmpeg 的吞吐(rawvideo 管道 / 分块);④长片导出耗时(全程可取消 + 进度)。
- **缓解**:全程 flag + ffmpeg 老路 fallback,像现在 compositor 一样灰度;每阶段独立验证 + 采样帧 pixel-diff 回归;导出代理可缓存复用。

## 里程碑价值

- P0+P1 落地即把**预览变成权威画面**,现报的画中画/黑屏在 P1 对着 canvas 修掉——不必等整条编码链。
- P2–P4 让**导出复用同一合成器**,parity 从根上消除;老 ffmpeg 路作安全网灰度退役。
