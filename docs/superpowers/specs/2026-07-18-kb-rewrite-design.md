# 知识库彻底重写设计(Dify 式 datasets + Neo4j 关联知识图谱)

> **归档状态：已废弃，未实现。** Mosael 当前不提供知识库能力，也不保留知识库路由、事件或兼容分支。
> 本文只保存 2026-07-18 的历史探索，不能作为当前产品或架构说明；当前事实以
> [ARCHITECTURE.md](../../ARCHITECTURE.md) 与官网文档为准。

日期:2026-07-18。以下内容是当时方案的原始记录。

## 背景与目标
现状:扁平的「工作区级文档列表」(note/url/file)→ `KbChunk` 分块 → FTS5(trigram + BM25),可选 Milvus/Neo4j 层默认关闭。痛点:交互差、**无法做检索测试**、看不到分块、无处理状态、错误直接把原始 JSON 漏到前端。

目标(用户确认):**多知识库(datasets)+ 完整 Dify 式 + Neo4j 关联知识图谱增强**。检索核心仍是 SQLite FTS5(不强上外部检索 SaaS),向量为可选既有层;Neo4j 知识图谱为一等增强(优雅降级:无 Neo4j 时纯 FTS,图谱标签页显示"配置后启用")。

> 注:这**推翻**了旧记忆「知识库架构」里"拒绝外部检索服务"的表述——用户现在明确要 Neo4j 自托管知识图谱。Milvus 向量仍为可选。

## 数据模型(重建 KB 三表)
- **`KbDataset`**(新):`id, workspace_id(FK cascade), name, description`,检索设置 `top_k=5, score_threshold(nullable float), retrieval_mode('fts'|'hybrid')`,分块设置 `chunk_size=500, chunk_overlap=60`,`graph_enabled(bool)`,`created_at, updated_at`。
- **`KbDocument`**:去掉 `workspace_id` 直挂,改挂 `dataset_id(FK cascade)`(仍存 workspace_id 冗余便于鉴权/查询);新增真实状态 `status: queued|processing|completed|error` + `error(Text)`、`chunk_count(int)`、`char_count(int)`。保留 `title, source_type, source_ref, content, summary, tags`。
- **`KbChunk`**:新增 `dataset_id`、`char_count`。保留 `document_id, chunk_index, text`。
- FTS 虚表 `kb_chunks_fts` 增加 `dataset_id` UNINDEXED 列(按库过滤)。
- **迁移守卫**(`core/db.py` init_db):若 `kb_datasets` 表不存在 → DROP 旧 `kb_documents/kb_chunks/kb_chunks_fts` → create_all 重建。幂等,只跑一次。

## 后端 API
- 数据集:`GET/POST /kb/datasets`(list/create)、`GET/PATCH/DELETE /kb/datasets/{id}`(PATCH 改分块设置 → 重索引全库)。
- 文档(挂在库下):`GET /kb/datasets/{id}/documents`(带 status/chunk_count)、`POST .../documents`(note)、`.../import-url`、`.../import-file`、`GET/PATCH/DELETE /kb/documents/{id}`、**`GET /kb/documents/{id}/chunks`**(分块可见)、**`POST /kb/documents/{id}/reindex`**。
- **`POST /kb/datasets/{id}/retrieval-test`** → `{query, top_k?, score_threshold?}` → 命中分块 + **score** + 来源文档 + snippet + `from_graph` 标记。← 召回测试。
- 图谱:**`GET /kb/datasets/{id}/graph`**(实体+边,给可视化)、`GET /kb/documents/{id}/graph`(单文档子图)。
- 工作流 `kb_search` 节点:新增 `dataset_id` 配置(下拉选库),不再全工作区。

## 摄取管线(异步 + 状态)
导入即建 doc `status=processing`,后台线程(复用现有 daemon 模式):转换(MinerU/markitdown/text)→ 分块(按 dataset 分块设置)→ 写 FTS(+ 可选向量)→ 若 `graph_enabled` 则 LLM 抽实体写 Neo4j → `completed`;失败落 `status=error` + `error` 文案(前端可见、可重试,不再 422 死路)。前端轮询状态。大文件(MinerU 可达数百秒)不再阻塞请求 = 修复"交互很差"的核心。

## 检索(GraphRAG-hybrid)
`search(dataset_id, query, top_k, threshold)`:FTS 排名(+ 可选向量)RRF 融合到分块级 → 若图谱开:top 文档经 `expand_related_chunks`(共享实体)半权并入 → 每文档取最佳分块 → 阈值过滤 → 返回。召回测试面板标出哪些来自图谱扩展。

## 前端(Dify 式三级)
- **知识库列表**:dataset 卡片 + 新建。
- **知识库详情**(标签):**文档**(status 角标 + chunk 数 + 导入)/ **召回测试**(query → 带分数的分块结果)/ **知识图谱**(力导向图,点实体→相关文档/分块;无 Neo4j 显示"配置后启用")/ **设置**(名称/描述、分块设置、检索设置、图谱开关)。
- **文档详情**:元数据/标签 + 正文 + **分块列表**(看清怎么切的)。
- 全程解析后端 `detail` 错误,不再漏原始 JSON。
- 图可视化库:待定(优先 react-force-graph-2d 或复用已有依赖)。

## 基础设施
- Neo4j:加 `docker-compose` 片段起本地 Neo4j + 配置接线(`neo4j_uri/user/password` 已在 config)。实体抽取需 LLM(复用 `kb_embedding_vendor` 或工作流 LLM 供应商)。
- 无 Neo4j / 无 LLM → 图谱功能静默降级,KB 纯 FTS 照常。

## 分片实现顺序(每片一提交,先后端后前端,逐片验证)
1. Schema 重建(KbDataset + doc/chunk 字段)+ 迁移守卫
2. 数据集 CRUD + 设置
3. 异步摄取管线 + 状态
4. 检索测试端点
5. 分块 API
6. 摄取时建图 + `/graph` 端点
7. 前端:知识库列表 → 详情(文档/召回测试/设置)
8. 前端:文档详情 + 分块
9. 前端:知识图谱可视化
10. 工作流 `kb_search` 节点接 dataset

## 风险/取舍
- 异步管线需要一个后台执行器 + 状态轮询(已有 daemon-thread 先例)。
- 图谱质量依赖 LLM 抽实体;无 LLM 时图为空(降级)。
- 图可视化在大图上需限制节点数(top-N 实体)。
