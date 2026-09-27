"""Mosael 的文件格式:插件包、工作流文件、画板快照。

纯 Python、零依赖、不认识 HTTP 也不认识数据库。桌面后端(`backend/`)和社区服务(`community/`)都依赖它
(ADR 0026):用户点「从文件安装」时过的规则,和社区上架时过的,是同一份。

- `plugin_manifest`:清单的解析与校验;
- `plugin_archive`:插件 zip 的安全检查(符号链接、路径穿越、大小上限)与读取;
- `plugin_index`:插件市场索引里的一条;
- `versions`:版本号的先后;
- `effects`:工具后果的词表;
- `workflow_file`:工作流文件的信封与图的骨架;
- `board_snapshot`:画板快照;
- `i18n`:以上报错的文案与语言。
"""

__version__ = "0.1.0"
