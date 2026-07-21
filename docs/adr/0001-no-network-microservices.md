# 不做网络微服务;解耦目标是「可拆而未拆」

Mibu 是本地优先桌面应用:单机上把后端拆成多个 HTTP 服务只会引入序列化、版本兼容、部分失败与分布式取消,而收益(独立伸缩/部署)在单机上不存在;SQLite 单写者也决定了数据无法按服务切开。剪辑内核(SequenceOperation + revision + 撤销)必须保持单事务原子性,永远不跨进程拆。

我们选择的形态是**微内核 + 卫星进程**:后端是唯一事实源,重活出进程(发布执行器 / sidecar / ASR·TTS 解释器 / ffmpeg / 插件),接缝画在进程边界上、通信协议显式化(见 ADR-0002)。「多机」是部署选项(把某个 job kind 翻成 external 执行模式),不是代码结构。团队模式扩容时优先:SQLite → Postgres、计算 kind → external worker;仍不引入消息中间件——jobs 表就是队列。

**Considered options**:按领域拆 HTTP 微服务(剪辑/渲染/发布各一)— 拒绝,理由如上;引入 broker(Redis/RabbitMQ)— 拒绝,claim/report 拉取模式已覆盖需求且多一个常驻依赖违背本地优先。
