# 预览与导出一致性靠契约,不靠合并成一个渲染器

预览必须在浏览器里本地同步跑到 60fps、并且渲染尚未提交到后端的拖拽草稿;导出必须无头、在后端、
可被外部 worker 认领跑在别的机器上([ADR-0002](0002-claim-report-worker-protocol.md))。两个约束
各自成立,合起来决定了画面模型**必然存在于两种语言里**——「只有一份实现」不是可选项。因此一致性
由**契约 + 语言中立语料**保证:`contracts/scene-cases.json` 同时驱动 `sceneModel.parity.test.ts`
与 `test_scene_parity.py`,任一侧改了语义而另一侧没跟上,两边 CI 都会红。语义边界按「谁是权威」
划分:**可见层/z 序/base 归属必须逐字一致**(所有已发生的 parity bug 都在这里),**调色则 ffmpeg
权威、预览近似**并在 UI 明示(LUT 提示已写明预览不显示)。

因此**放弃方案 Y**(canvas 合成导出帧、ffmpeg 只编码)。它确实能做到几何逐像素一致,但代价是结构性的:
①导出会丢掉 ffmpeg 独有的色阶曲线与 3D LUT——`url(#svg-filter)` 在 OffscreenCanvas 上不解析(浏览器
既定限制),canvas 2D 也没有 3D LUT 等价物,等于把权威从高保真的一侧换到低保真的一侧;②帧由浏览器
产出,`MOSAEL_EXTERNAL_JOB_KINDS=render` 的外派能力失效,团队/远程后端模式下不可用;③1080p30
十分钟约 149 GB 原始 RGBA 需要跨进程传输。换库也不解决:Diffusion Studio / Rendley 只替换浏览器侧
合成器,不会让后端 ffmpeg 跟着一致;Remotion 是唯一真正 by-construction 的方案,但需商业授权、是
「React 组件→视频」范式(等于重写渲染层),且同样没有 3D LUT。**库提供能力,不消除重复**——而重复
才是病根(`_read_transform` 原注释「Mirrors the frontend readTransform」即自白)。

对「实时预览无法逐像素精确」的补充答案沿用行业惯例(PR / DaVinci):实时预览是快速近似,需要精确帧时
走**真正的导出管线**渲一段来看,而不是让两套近似互相追。

方案 Y 的未接线代码(`OfflineFrameRenderer`、`OfflineVideoSource`、`frame_encoder`、全分辨率导出代理
及其路由)已随本决定删除:留着一堆有测试、看着像承重、实际零调用且会持续与 `scenePaint` 语义漂移的
代码,比删掉更贵。git 历史保留了它们,日后若上 WebGL 调色补齐保真度、并解决外派与传输量问题,可以
从这里取回重启。
