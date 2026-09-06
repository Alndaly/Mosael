# claim/report 拉取协议是唯一的外部执行契约

任何跨进程执行的任务(今天的发布,将来的渲染/转写)都走同一个拉取式契约:worker 主动 `claim`(CAS 原子认领)→ `report`(富状态回报)→ `heartbeat`;鉴权用本地文件下发的 worker key(浏览器读不到本地文件,这是真正的信任边界);后端从不反向连接 worker。已终态(含用户取消)的 job 不被后到的回报复活。

选拉取而非推送/broker:worker 可跨后端重启存活、NAT 友好、无常驻中间件;这正是发布执行器在生产里验证过的模式。job kind 经 `register_external_kind()` 或 `MOSAEL_EXTERNAL_JOB_KINDS` 声明 external 执行模式后,通用通道 `/api/jobs/worker/*` 即可认领——把渲染挪到 GPU 机器是配置,不是重构。publish 因历史契约保留专用通道 `/api/publish/worker/*`(任务粒度是 PublishTask,含账号巡检),语义与通用通道一致。

通用 worker 的认领现在附带持久化的 `lease_token`、`lease_expires_at`（UTC），租约有效期 60 秒。worker 必须在 `report` 中原样带回 token，并至少每 20 秒发一次 heartbeat：`{"worker":"同认领时的标识","claims":[{"job_id":"…","lease_token":"…"}]}`。heartbeat 返回 `renewed` job id 列表；未续上的执行应停止。进度回报也会续租。只发在线心跳、不携带具体认领，不延长任务租约。

后台定时扫描、启动恢复和 worker 请求都会收尾过期任务，并取消它的派生任务。失联任务标为失败，旧结果不得复活；不自动重新执行，避免重复计费或重复外部操作。尚未认领的排队任务及有效租约跨重启保留。升级前没有租约的运行中通用任务按最后更新时间给予 60 秒窗口；旧 worker 需按新契约携带 token。发布执行器继续使用专用 PublishTask 通道，通用 claim 不领取 publish。
