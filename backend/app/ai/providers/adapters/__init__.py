"""供应商与平台协议的具体 Adapter Implementation。

目录按连接协议组织；一家供应商横跨多种能力时，在自己的目录内再按 image、video、speech
拆分。调用方不应从这里选择 Adapter，而应通过 ``app.ai.providers`` 的公共 Interface。
"""
