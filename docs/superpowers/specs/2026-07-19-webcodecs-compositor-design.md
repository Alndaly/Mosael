# WebCodecs 预览合成器 — 设计

日期: 2026-07-19
状态: 已定范围(P1+P2+P3 一次到位,代理媒体纳入),待实现

## 问题

当前预览播放引擎(`Monitor.tsx` + `MonitorElement.tsx` + `AudioElement.tsx`)是「每条激活片段一个 HTML 媒体元素、各自 `currentTime` seek、40ms interval 驱动主时钟」的模型:

- N 个 `<video>` 各自独立解码 → 多轨时同时抢 GPU 解码器,浏览器合成器反复重排。
- seek 昂贵;元素间无帧级同步;transform/opacity 靠 CSS 叠层。
- 结果:多轨播放明显掉帧卡顿。

专业 NLE(Premiere / DaVinci)是**单一解码 → GPU 合成 → 主时钟**一条流水线。本设计把预览引擎替换为该模型。

## 关键决策(不可逆,先定)

1. **代理优先(proxy-first)。** 导入视频时后台转一份 720p H.264 mp4 代理(短 GOP、faststart)。合成器**只解码代理**,导出仍用原片。
   - 好处:`VideoDecoder` 的输入永远是已知良好的 avc mp4,解码轻、seek 快、demux 简单;规避了"源可能是 webm/hevc/奇怪封装"的全部风险。
   - 代理未就绪或生成失败的片段 → 回退到旧的 `<video>` 元素路径(优雅降级)。

2. **解码:mp4box.js demux → `VideoDecoder`。** mp4box 提供 sample table + sync samples(关键帧),支撑从最近关键帧 seek。代理的短 GOP 让 seek 便宜。

3. **合成面:canvas 2D(先)。** `ctx.drawImage(VideoFrame, …)` + `translate/rotate/scale/globalAlpha` 一次性完成 z-order、transform、opacity;色彩分级用 `ctx.filter`(Chromium 支持 filter 函数与 `url(#svg)` 引用)近似导出端。WebGL 留作后续精度优化,非首版。

4. **主时钟:`AudioContext.currentTime`(P3 起)。** 播放时音频图驱动时钟,视频合成 rAF 循环读时钟挑帧 → 音画同步。暂停/拖拽时时钟直接取 store `playhead`。

5. **集成边界:** `Monitor` 的画框内容从"叠层元素"换成**单个 `<canvas>`**。新 `PlaybackEngine` 类拥有解码器、音频图、时钟、绘制。字幕/暗角/transform 手柄/示波器仍是 canvas 之上的 DOM 覆盖层(它们是 UI,不是媒体)。

6. **特性开关 + 回退。** 一个 flag 控制新引擎;WebCodecs 不可用、或片段无代理且源不可 demux 时,回退旧路径。保证灰度期间应用始终可用。

## 分片(每片独立验证、独立提交)

- **S0 代理管线(后端,本片不动预览):** 视频资产导入 → 异步 Job 转 720p H.264 代理落在资产目录;`Asset.media_info` 暴露 `proxy_key` + `proxy_status`;启动 reconcile 补做缺失代理。验证:导入视频→代理文件生成→接口返回代理 url。
- **S1 引擎骨架 + 单轨视频:** `PlaybackEngine` + mp4box demux + `VideoDecoder` + 帧环形缓存 + canvas 2D 画底轨;rAF 时钟同步 store playhead;seek/scrub;`frame.close()`。特性开关,单视频轨,图片用 drawImage。验证:单轨 canvas 顺滑播放、seek 准。
- **S2 多轨合成:** 所有激活视频片段按 z-order(顶轨在上)带 transform/opacity 合成到同一 canvas;移植色彩分级。验证:红/绿 z-order + PiP transform 在 canvas 上正确;多轨不再卡(测 fps)。
- **S3 WebAudio 主时钟:** 每条激活音频 + 视频片段音频进音频图(`AudioBufferSourceNode`+`GainNode`);主时钟改 `AudioContext`;gain/mute/solo/duck;音画同步。验证:多音轨 + 分离音频同步播放;scrub 仍可用。
- **S4 缓存/性能调优 + 回退打磨:** 预解码前瞻、解码器池、负载下丢帧、卸载时 teardown、内存上限。测 fps vs 旧路径。

## 非目标 / 稍后

- WebGL 合成与 LUT 精确预览(canvas 2D 的 `ctx.filter` 先顶)。
- 导出路径不变(仍走后端 FFmpeg render_plan;导出用原片)。
- 字幕/暗角保持 DOM 覆盖,不进 canvas。
