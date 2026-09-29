"""能力描述符的数据:按介质 / 厂商分文件。

唯一的入口是 domain/generation/catalog —— 它重新导出这里的每一个名字(**同一个对象**,
档案名册按 id() 反查),并持有所有函数。这里的模块不回头 import catalog。
"""
