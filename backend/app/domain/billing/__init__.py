"""计价与记账:用量事件(`usage`,两张表的拥有方)、时段价(`price_schedule`)、内置价目表
(`price_reference`)、按目录与价目表给连接预填计价规则(`pricing_prefill`)。

这里只写说明,不 import、不定义任何东西:调用方从具体的子模块取(见 tests/test_import_layering ——
包的 `__init__` 一转发子模块,子模块之间互相引用就会经它成环)。
"""
