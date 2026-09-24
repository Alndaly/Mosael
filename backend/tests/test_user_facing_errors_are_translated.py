"""棘轮:后端报给人看的错误**不写死中文句子**。

领域错误用 `core.i18n.LocalizedError(key, **params)`,路由里直接写的 `HTTPException(detail=…)`
用 `core.i18n.tr(key, **params)`。两者都按**这次请求**的语言翻(中间件把 Accept-Language 放进
ContextVar)。写死的中文在英文界面里原样弹出来 —— Blender 互通的报错就是这么被发现的:半句
中文、半句上游透传的英文。

扫的是 `raise …(`、`HTTPException(`、`detail=` 所在的行里有没有中文字符。`LEFT` 是存量,
**只减不增**:哪个文件翻完了就把它从这里删掉(或把数字改小),棘轮前进一格。

看不见的:句子拼在别的变量里再 raise、或者跨了几行的字符串。所以这是**下限**。
"""
from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
CJK = re.compile(r"[一-鿿]")
ERROR_LINE = re.compile(r"\braise \w[\w.]*\(|HTTPException\(|\bdetail=")


def _count() -> Counter[str]:
    found: Counter[str] = Counter()
    for path in APP.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0] if not line.lstrip().startswith(("'", '"')) else line
            if ERROR_LINE.search(code) and CJK.search(code):
                found[str(path.relative_to(APP))] += 1
    return found


#: 还没翻完的:文件 → 还剩几行。**只减不增。**
LEFT: dict[str, int] = {
    "ai/providers/adapters/alibaba/dashscope/image.py": 1,
    "ai/providers/adapters/alibaba/dashscope/speech.py": 3,
    "ai/providers/adapters/alibaba/dashscope/video.py": 1,
    "ai/providers/adapters/bytedance/ark/image.py": 1,
    "ai/providers/adapters/bytedance/ark/video.py": 1,
    "ai/providers/adapters/bytedance/volcano/podcast.py": 10,
    "ai/providers/adapters/bytedance/volcano/speech.py": 4,
    "ai/providers/adapters/comfyui/generation.py": 8,
    "ai/providers/adapters/evolink/generation.py": 11,
    "ai/providers/adapters/google/veo.py": 1,
    "ai/providers/adapters/kuaishou/kling/elements.py": 6,
    "ai/providers/adapters/kuaishou/kling/video.py": 1,
    "ai/providers/adapters/local/deepfilter_denoise.py": 4,
    "ai/providers/adapters/local/demucs_separation.py": 4,
    "ai/providers/adapters/local/ffmpeg_denoise.py": 3,
    "ai/providers/adapters/local/rnnoise_denoise.py": 2,
    "ai/providers/adapters/microsoft/edge_speech.py": 3,
    "ai/providers/adapters/minimax/video.py": 5,
    "ai/providers/adapters/openai/image.py": 1,
    "ai/providers/adapters/openai/speech.py": 2,
    "ai/providers/contracts/denoise.py": 1,
    "ai/providers/contracts/generation.py": 3,
    "ai/providers/registry.py": 5,
    "ai/runtime/asr_models.py": 6,
    "ai/runtime/denoise_models.py": 3,
    "ai/runtime/f5_models.py": 3,
    "ai/runtime/install_state.py": 1,
    "ai/runtime/separation_models.py": 4,
    "ai/runtime/tts_models.py": 6,
    "ai/runtime/worker_pool.py": 4,
    "ai/runtime/workers/tts.py": 4,
    "ai/sidecar/adapters.py": 13,
    "api/routes/admin.py": 1,
    "api/routes/agent.py": 8,
    "api/routes/agent_browser.py": 1,
    "api/routes/agent_credentials.py": 2,
    "api/routes/agent_tools.py": 2,
    "api/routes/asr.py": 3,
    "api/routes/assets.py": 6,
    "api/routes/auth.py": 5,
    "api/routes/browser_profiles.py": 2,
    "api/routes/collaboration.py": 3,
    "api/routes/denoise.py": 1,
    "api/routes/generation.py": 4,
    "api/routes/job_worker.py": 1,
    "api/routes/notes.py": 5,
    "api/routes/notifications.py": 1,
    "api/routes/oauth.py": 4,
    "api/routes/plugins.py": 2,
    "api/routes/scenes.py": 1,
    "api/routes/separation.py": 1,
    "api/routes/session_groups.py": 1,
    "api/routes/settings/generation_profiles.py": 6,
    "api/routes/settings/provider_defaults.py": 3,
    "api/routes/settings/provider_models.py": 2,
    "api/routes/settings/provider_oauth.py": 4,
    "api/routes/settings/provider_pricing.py": 2,
    "api/routes/settings/provider_profiles.py": 1,
    "api/routes/shares.py": 1,
    "api/routes/voices.py": 10,
    "api/routes/workflows.py": 4,
    "api/routes/workspaces.py": 2,
    "core/http_retry.py": 1,
    "core/i18n.py": 1,
    "domain/agent/confirmable/automation.py": 3,
    "domain/agent/confirmable/blender.py": 4,
    "domain/agent/confirmable/deletion.py": 4,
    "domain/agent/confirmable/external.py": 5,
    "domain/agent/confirmable/generation.py": 1,
    "domain/agent/confirmable/media.py": 14,
    "domain/agent/confirmable/registry.py": 3,
    "domain/agent/host.py": 2,
    "domain/agent/judge.py": 3,
    "domain/agent/login.py": 2,
    "domain/agent/memory.py": 5,
    "domain/agent/plan.py": 2,
    "domain/agent/questions.py": 14,
    "domain/ai_chat.py": 5,
    "domain/analysis/service.py": 15,
    "domain/assets/from_url.py": 3,
    "domain/assets/plugin_bridge.py": 4,
    "domain/assets/video_gif.py": 4,
    "domain/blender/worker.py": 5,
    "domain/boards/actions.py": 3,
    "domain/boards/canvas.py": 45,
    "domain/boards/ops.py": 9,
    "domain/boards/trim.py": 7,
    "domain/browser/__init__.py": 13,
    "domain/collaboration.py": 10,
    "domain/denoise.py": 6,
    "domain/fonts.py": 4,
    "domain/generation/operations.py": 10,
    "domain/generation/prompt_optimizer.py": 5,
    "domain/generation/public_links.py": 4,
    "domain/generation/resolution.py": 6,
    "domain/generation/runner.py": 4,
    "domain/host_code.py": 4,
    "domain/jobs.py": 5,
    "domain/luts.py": 8,
    "domain/markers.py": 15,
    "domain/members.py": 8,
    "domain/note_types.py": 4,
    "domain/notes.py": 11,
    "domain/notifications.py": 1,
    "domain/permissions.py": 2,
    "domain/plugins/artifacts.py": 8,
    "domain/plugins/capability_defaults.py": 2,
    "domain/plugins/inputs.py": 2,
    "domain/plugins/instances.py": 4,
    "domain/plugins/manifest.py": 3,
    "domain/plugins/mcp_bridge.py": 7,
    "domain/plugins/media_bridge.py": 2,
    "domain/plugins/oauth.py": 6,
    "domain/plugins/packages.py": 2,
    "domain/plugins/registry.py": 14,
    "domain/plugins/runtime.py": 14,
    "domain/plugins/state.py": 2,
    "domain/plugins/tools.py": 4,
    "domain/poem.py": 3,
    "domain/provider_auth.py": 5,
    "domain/provider_health.py": 1,
    "domain/provider_models.py": 1,
    "domain/provider_presets.py": 9,
    "domain/provider_quota.py": 17,
    "domain/providers.py": 3,
    "domain/publish/__init__.py": 6,
    "domain/publish/copy.py": 4,
    "domain/publish/worker.py": 4,
    "domain/sandbox/__init__.py": 9,
    "domain/scene_render/__init__.py": 4,
    "domain/scene_render/model_mesh.py": 7,
    "domain/scenes.py": 8,
    "domain/scheduler/executors.py": 2,
    "domain/scheduler/operations.py": 2,
    "domain/separation.py": 6,
    "domain/sequences/history.py": 3,
    "domain/sequences/operations.py": 6,
    "domain/sequences/undo/__init__.py": 4,
    "domain/sequences/undo/rows.py": 1,
    "domain/sequences/undo/tracks.py": 1,
    "domain/sharing.py": 1,
    "domain/voices/engine_catalog.py": 3,
    "domain/voices/original_audio.py": 4,
    "domain/voices/subtitle_dub.py": 9,
    "domain/voices/transcription.py": 8,
    "domain/voices/voices.py": 20,
    "domain/websearch.py": 6,
    "domain/workflows/ai_edit.py": 1,
    "domain/workflows/executors/__init__.py": 2,
    "domain/workflows/field_options.py": 1,
    "domain/workflows/graph_ops.py": 3,
    "domain/workflows/revisions.py": 5,
    "integrations/feishu/service.py": 6,
    "integrations/volc_openapi.py": 2,
    "media/audio_io.py": 2,
    "media/render_executor.py": 2,
    "media/still.py": 3,
    "media/video_gif.py": 5,
}


def test_没有新的写死中文的报错() -> None:
    now = _count()
    grown = {f: (LEFT.get(f, 0), n) for f, n in now.items() if n > LEFT.get(f, 0)}
    assert not grown, (
        "这些文件的报错里多出了写死的中文(存量 → 现在)。用 LocalizedError / tr 加一个文案 key:\n  "
        + "\n  ".join(f"{f}: {a} → {b}" for f, (a, b) in sorted(grown.items()))
    )


def test_存量只减不增() -> None:
    now = _count()
    stale = {f: (n, now.get(f, 0)) for f, n in LEFT.items() if now.get(f, 0) < n}
    assert not stale, (
        "这些文件已经翻掉了一些,把 LEFT 里的数字改小(0 就删掉那一行),让棘轮前进一格:\n  "
        + "\n  ".join(f"{f}: {a} → {b}" for f, (a, b) in sorted(stale.items()))
    )
