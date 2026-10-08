"""**同步**生成接口(一次 POST 等到图出来:OpenAI 图像、方舟 Seedream、通义千问改图)共用的超时。

读超时的意思是请求已经送到、对方在做,只是没在我们等的时间里答完 —— 对方多半照样做完、照样扣钱,而我们手里什么都
没有(同步接口没有回执,事后取不回)。此前是 120 / 180 秒:gpt-image-1 高质量一次四张就过了这条线,任务判失败、记
「未扣费」,用户照提示重来就是再付一次(GEN-6)。等久一点的代价只是失败来得晚一点。各家实际耗时的上限没有核实过,
这里按「明显比最慢的一次长」取。
"""

from __future__ import annotations

#: 等回答最多等多久。
SYNC_GENERATION_READ_SECONDS = 600.0
#: 连不上多久放弃:请求还没出门,放弃是安全的,不必陪着等十分钟。
SYNC_GENERATION_CONNECT_SECONDS = 30.0


def sync_generation_timeout() -> tuple[float, float, float, float]:
    """交给 RetryingClient 的 `timeout`:httpx 认的四元组 (连接, 读, 写, 等连接池)。写也放宽 —— 参考图随请求一起上传。"""
    return (
        SYNC_GENERATION_CONNECT_SECONDS,
        SYNC_GENERATION_READ_SECONDS,
        SYNC_GENERATION_READ_SECONDS,
        SYNC_GENERATION_CONNECT_SECONDS,
    )
