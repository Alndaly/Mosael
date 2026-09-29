"""AI 供应商这一族:用户的连接(`connections` 建改删、`selection` 按人选一条可用的并解析钥匙)、
每个人自己的钥匙(`credentials`)与订阅登录(`auth`)、连接下的模型行(`models`)与每项能力的默认模型
(`defaults`)、供应商预设(`presets`)、额度(`quota`)、探活(`health`)、发给运行时的参数(`runtime`、
`model_limits`、`thinking`、`structured_output`)。

这里只写说明,不 import、不定义任何东西:调用方从具体的子模块取(见 tests/test_import_layering ——
包的 `__init__` 一转发子模块,子模块之间互相引用就会经它成环)。调用处常写成
`from app.domain.providers import models as provider_models`,本地名照旧。
"""
