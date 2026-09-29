"""后端文案 · AI 对话(分区 B1)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # ---- B1 · 04_aichat ----
    "aiChat_labelDefault": {
        "zh": "AI 调用",
        "en": "AI call",
    },
    "aiChatErr_http": {
        "zh": "{label}失败:{status} {detail}（模型 {model}）",
        "en": "{label} failed: {status} {detail} (model {model})",
    },
    "aiChatErr_network": {
        "zh": "{label}失败(网络/连接):{detail}",
        "en": "{label} failed (network/connection): {detail}",
    },
    "aiChatErr_networkRetried": {
        "zh": "{label}失败(网络/连接,已重试 {tries} 次仍失败):{detail}",
        "en": "{label} failed (network/connection, still failing after {tries} retries): {detail}",
    },
    "aiChatErr_badShape": {
        "zh": "{label}失败:供应商返回的结构不认识({detail})",
        "en": "{label} failed: the provider returned a response in an unrecognized shape ({detail})",
    },
    "aiChatErr_gatewayNoClient": {
        "zh": "{label}失败:OAuth Gateway 不支持复用调用方 HTTP 连接",
        "en": "{label} failed: the OAuth gateway can't reuse the caller's HTTP connection.",
    },
    "aiChatErr_failed": {
        "zh": "{label}失败:{detail}",
        "en": "{label} failed: {detail}",
    },
    "aiChatDowngrade_rejected": {
        "zh": "供应商明确拒绝了这一档",
        "en": "The provider explicitly rejected this tier",
    },
    "aiChatDowngrade_empty": {
        "zh": "这一档下返回了空正文",
        "en": "This tier returned an empty body",
    },
    "providerErr_connectionMissing": {
        "zh": "指定的供应商配置不存在或已停用",
        "en": "The selected provider connection doesn't exist or is disabled.",
    },
    "providerErr_noConnection": {
        "zh": "没有可用的 AI 供应商连接,请先在设置里添加并配置",
        "en": "No AI provider connection is available. Add and configure one in Settings first.",
    },
    "providerErr_noKey": {
        "zh": "供应商「{name}」还没有配置你的密钥,请先在设置里填写",
        "en": "Provider \"{name}\" doesn't have your key yet. Add it in Settings first.",
    },
}
