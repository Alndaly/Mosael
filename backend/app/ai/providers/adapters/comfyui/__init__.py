"""ComfyUI:**一家跨两种能力**,所以不进 image/ 也不进 video/。

它是同一个类实例化两次(`ComfyUIProvider("image")` / `("video")`)—— 出图还是出视频由工作流
决定,不由适配器决定。硬塞进按能力分的目录里,要么把它拆成两个文件、要么在一边留个指向另一边
的壳,两样都比让它自成一组更糟。

另一点也和别家不同:它是**本地**服务,所以还带一个 HTTP 客户端(client.py)和排队进度上报,
而不是"提交到云端再轮询"。
"""

from app.ai.providers.adapters.comfyui.provider import (
    DEFAULT_BASE,
    DEFAULT_TEMPLATE,
    OUTPUT_KEYS,
    ComfyUIProvider,
    collect_output_files,
    substitute_placeholders,
)

__all__ = [
    "DEFAULT_BASE",
    "DEFAULT_TEMPLATE",
    "OUTPUT_KEYS",
    "ComfyUIProvider",
    "collect_output_files",
    "substitute_placeholders",
]
