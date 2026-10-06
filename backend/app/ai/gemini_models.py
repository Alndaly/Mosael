"""Gemini API(AI Studio)上的哪些模型是**对话**模型。

同一把 Key 下 `GET /v1beta/models` 列出的远不只是对话模型:Veo(视频)、Imagen 与 `gemini-*-image`(出图)、
`gemini-embedding-*`(向量)、`*-tts`(念字)、`*-live*` 与 `*-native-audio-*`(实时音频)、`gemini-omni-*`(视频生成)、
`*-transcribe*`(转写)、`gemini-robotics-*`、`*-computer-use-*` 都在里面。按「支持 generateContent」筛不干净 ——
出图的 `gemini-*-image`、Lyria、TTS、转写模型都支持 generateContent。

所以还要按名字认,而这条规则**两处共用**:目录只列对话模型(`ai/model_catalog` 的 Gemini 那一支),模型行没写能力时
也照它认(`domain/providers/models.evidenced_capabilities`)。只有一处的话,手动加进来的 `imagen-4.0-generate-001`
会被预设兜底成对话模型,出现在智能体的模型下拉里,选了必然失败。

判据(2026-10 对照官方模型页与价目页 https://ai.google.dev/gemini-api/docs/pricing):

  1. 以 `gemini-` 开头 —— Imagen、Veo、Lyria、Gemma、Deep Research(走 Interactions API)都不是;
  2. 名字按 `-` 切开后不含下面这几个词 —— 它们各自对应一类不是对话的模型。
"""

from __future__ import annotations

#: 名字里出现这几个词(按 `-` 切开后整段相等)就不是对话模型。
_NOT_CHAT_PARTS = frozenset({
    "image",  # gemini-2.5-flash-image、gemini-3-pro-image、gemini-3.1-flash(-lite)-image —— 出图(Nano Banana)
    "embedding",  # gemini-embedding-2 —— 向量
    "tts",  # gemini-3.8-flash-tts、gemini-2.5-flash-preview-tts —— 念字
    "live",  # gemini-3.8-live、gemini-3.1-flash-live-preview、gemini-3.5-live-translate-preview —— 只有实时(bidi)接口
    "audio",  # gemini-2.5-flash-native-audio-* —— 实时音频
    "transcribe",  # gemini-3.5-transcribe(-live) —— 语音转写
    "omni",  # gemini-omni-1.1-flash —— 视频生成与编辑
    "computer",  # gemini-2.5-computer-use-preview-* —— 操作电脑的专用模型
    "robotics",  # gemini-robotics-er-2-preview —— 机器人
})


def is_chat_model(model_id: str) -> bool:
    """这个 id 是不是一个能拿来对话(含工具调用)的 Gemini 模型。`models/` 前缀可有可无。"""
    name = (model_id or "").strip().lower().removeprefix("models/")
    if not name.startswith("gemini-"):
        return False
    return not (set(name.split("-")) & _NOT_CHAT_PARTS)
