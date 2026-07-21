# Mibu

本地优先的 AI 视频创作工作室(Electron 桌面应用)。这份文档定义架构讨论用的统一语言——
子系统文档见 docs/,决策记录见 docs/adr/。

## Language

### 进程与协议

**事实源(后端)**:
FastAPI 后端(127.0.0.1:8800),持有全部持久状态;前端、发布执行器、sidecar 都只是它的客户端。
_Avoid_: 服务端(团队模式语境除外)、server

**卫星进程**:
由壳或后端拉起、经显式协议与后端通信的独立进程(发布执行器 / agent sidecar / ASR·TTS 解释器 / ffmpeg / 插件 / 飞书 bot)。
_Avoid_: 微服务

**worker 协议**:
拉取式任务执行契约:claim(CAS 原子认领)→ report(富状态回报)→ heartbeat;后端从不反向连接 worker。
_Avoid_: 推送、回调、消息队列

**执行模式**:
job kind 的属性,决定由谁执行:`in_process`(守护线程,进程死任务亡)或 `external`(worker 协议驱动,跨重启存活)。声明权在各领域(`register_external_kind`),读取权在任务总线。

### 任务总线

**任务总线**:
`jobs` + `task_events` 两张表加 `app/domain/jobs.py` 的接口;一切耗时操作收敛为 job。
_Avoid_: 队列服务、调度中心

**派发(dispatch)**:
`dispatch_job`:领域描述「怎么跑」,总线决定「由谁跑」。

**准入槽**:
按 kind 的信号量并发上限(render 2 / ASR 1 / TTS 1 / 生成 4),防单机 OOM;external 模式下等价于 worker 侧并发容量。

### 工作流

**节点注册表(NODE_TYPES)**:
节点的元数据接缝:驱动校验、画布 UI、智能体提示。

**执行器注册表(executors/)**:
节点的行为接缝:每种节点类型一个执行器适配器,签名 `handler(db, workflow, config) -> dict`。与 NODE_TYPES 一一对应(锁步测试钉死)。

**引擎(engine.py)**:
纯 DAG 调度器:拓扑、并行、条件路由、取消边界、事件与进度。对具体领域零 import。

### 数据

**数据归属**:
每张表归一个领域模块所有,行创建只发生在拥有方(`app/domain/ownership.py`);跨领域需要新行时调用拥有方的领域函数。

**归属棘轮**:
`tests/test_data_ownership_ratchet.py`:存量越界冻结在 allowlist 只减不增;新增越界与修复后未删条目都会失败。

### 智能体

**工具注册表**:
`mcp_server.py` 是唯一工具定义处;`/api/agent/tools` manifest 派生它,所有 runtime(pi sidecar / MCP 客户端 / 飞书)从 manifest 生成工具,不再手写第二份。

**确认门控**:
变更工具的属性(manifest 的 `confirmation: true`):调用只创建待确认卡,用户批准后才执行;sidecar 对此类工具统一阻塞轮询。
_Avoid_: 按工具名硬编码确认逻辑

**供应商能力配置**:
`app/domain/providers.py` 暴露的 Adapter preset,按供应商/能力声明它支持哪些能力(chat / image / video / embedding / tts / podcast)以及设置页要收集哪些配置字段。前端只渲染后端声明的 `fields`,不要硬编码 `api_key/base_url/default_model` 这类通用凭据模型。
_Avoid_: 仅凭 vendor 文案推断能力

## Relationships

- 一个 **job** 属于一种 kind;kind 有且只有一个**执行模式**
- **引擎**只认**执行器注册表**;**执行器注册表**与**节点注册表**一一对应
- **卫星进程**经 **worker 协议**(external 类)或 stdio/subprocess(共生类)与**事实源**通信
- 每张表有且只有一个**数据归属**领域;**归属棘轮**守护它
- **供应商能力配置**只说明某个 adapter 需要哪些配置以及能进入哪些能力;能力的实际 HTTP/SDK 差异由该能力自己的 Adapter 接缝负责

## Example dialogue

> **Dev:**「我要加一种『视频翻译』节点,改哪里?」
> **架构:**「**节点注册表**加元数据,**执行器注册表**加一个执行器文件——**引擎**不动。如果它耗时,内部建 job 走**任务总线**;将来想让翻译跑在 GPU 机器上,把它的 kind 注册成 external **执行模式**就行,worker 经 **worker 协议**认领,领域代码不改。」

## Flagged ambiguities

- 「worker」曾同时指发布执行器与任意后台线程——现约定:**worker** 专指经 worker 协议认领任务的外部进程;进程内的叫守护线程/执行器。
- 「注册表」需带限定词:**节点注册表**(元数据)/ **执行器注册表**(行为)/ **工具注册表**(智能体)/ 平台注册表(发布)。
