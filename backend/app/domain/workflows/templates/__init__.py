"""官方工作流模板:每个模板一个模块,`catalog` 是目录与建图入口(见 ADR 0026)。

- `catalog`:模板清单、需求检查、按配置建图(此前的 `workflows/templates/catalog.py`);
- `model_choice`:模板里挑模型的形状 `ModelChoice` 与按能力的规划;`schemas`:各模板对话节点的 JSON Schema;
- `asset_prompts`:角色三视图、场景设计稿怎么画(整片与系列设定共用);`blockout`:搭 3D 白模布景的规矩(整片与画板「按文字搭 3D 场景」共用);
- 其余每个文件是一个(或一族)模板。

此前十几个 `templates_*.py` 平铺在 `workflows/` 下,靠前缀当命名空间(2026-11-14 审计 C2)。
"""
