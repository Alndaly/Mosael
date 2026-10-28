"""能力描述符的数据:按介质 / 厂商分文件。

数据从各个模块直接取;函数(查能力、档案名册)在 domain/generation_catalog —— 它 import 这里的对象
(**同一个对象**,档案名册按 id() 反查)。这里的模块不回头 import catalog。
"""
