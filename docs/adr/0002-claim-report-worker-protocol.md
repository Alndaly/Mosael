# claim/report 拉取协议是唯一的外部执行契约

任何跨进程执行的任务(今天的发布,将来的渲染/转写)都走同一个拉取式契约:worker 主动 `claim`(CAS 原子认领)→ `report`(富状态回报)→ `heartbeat`;鉴权用本地文件下发的 worker key(浏览器读不到本地文件,这是真正的信任边界);后端从不反向连接 worker。已终态(含用户取消)的 job 不被后到的回报复活。

选拉取而非推送/broker:worker 可跨后端重启存活、NAT 友好、无常驻中间件;这正是发布执行器在生产里验证过的模式。job kind 经 `register_external_kind()` 或 `MIBU_EXTERNAL_JOB_KINDS` 声明 external 执行模式后,通用通道 `/api/jobs/worker/*` 即可认领——把渲染挪到 GPU 机器是配置,不是重构。publish 因历史契约保留专用通道 `/api/publish/worker/*`(任务粒度是 PublishTask,含账号巡检),语义与通用通道一致。
