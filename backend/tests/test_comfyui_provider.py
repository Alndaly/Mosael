"""ComfyUI:零密钥的本地生成供应商。

The contract worth pinning: an arbitrary ComfyUI graph fits Open Studio's prompt→image call
through placeholder substitution (typed, injection-safe), the built-in template works on a
stock install by discovering the checkpoint live, and every failure a user can hit — bad
template JSON, no models, graph rejected, server down — surfaces as a message they can act
on rather than a raw HTTP error. All HTTP is mocked; the suite must not need a GPU.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.providers import get_provider
from app.ai.providers.adapters.comfyui import client as comfyui_client
from app.ai.providers.adapters.comfyui import provider as comfyui
from app.ai.providers.contracts.generation import GenerationRequest, ProviderContext, ProviderError
from app.ai.providers.adapters.comfyui import (
    DEFAULT_TEMPLATE,
    ComfyUIProvider,
    collect_output_files,
    substitute_placeholders,
)
from app.domain.generation.catalog import BUILTIN_MODELS
from tests.util import fresh_client


def ctx(extra: dict | None = None) -> ProviderContext:
    return ProviderContext(profile_id=None, vendor="comfyui", api_key="", base_url="", extra=extra or {})


def req(**params) -> GenerationRequest:
    return GenerationRequest(kind="image", model="workflow", prompt="海边的柴犬", parameters=params)


def test_registered_and_keyless() -> None:
    provider = get_provider("comfyui", "image")
    assert provider is not None
    assert provider.requires_credentials() is False, "a fresh install must be able to generate with zero config"


def test_builtin_catalog_offers_the_model() -> None:
    assert any(m["id"] == "comfyui:workflow:image" for m in BUILTIN_MODELS)


def test_vendor_preset_needs_no_api_key() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    vendors = client.get("/api/settings/provider-vendors").json()
    preset = next(v for v in vendors if v["vendor"] == "comfyui")
    assert "image" in preset["capability_ids"]
    assert not any(f.get("storage") == "api_key" for f in preset["fields"]), "ComfyUI has no key to ask for"


class TestPlaceholders:
    def test_exact_placeholder_keeps_the_raw_type(self) -> None:
        graph = {"3": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", "steps": "{{steps}}"}}}
        filled = substitute_placeholders(graph, {"seed": 42, "steps": 20})
        assert filled["3"]["inputs"]["seed"] == 42, "KSampler requires an int, not the string '42'"

    def test_embedded_placeholder_splices_text(self) -> None:
        graph = {"6": {"inputs": {"text": "masterpiece, {{prompt}}, 4k"}}}
        filled = substitute_placeholders(graph, {"prompt": "海边的柴犬"})
        assert filled["6"]["inputs"]["text"] == "masterpiece, 海边的柴犬, 4k"

    def test_quotes_and_backslashes_cannot_break_the_graph(self) -> None:
        """Substitution happens on the parsed tree — a hostile prompt is just a string."""
        graph = {"6": {"inputs": {"text": "{{prompt}}"}}}
        evil = 'she said "hi" \\ {"not": "json"}'
        assert substitute_placeholders(graph, {"prompt": evil})["6"]["inputs"]["text"] == evil

    def test_template_is_not_mutated(self) -> None:
        substitute_placeholders(DEFAULT_TEMPLATE, {"checkpoint": "x.safetensors"})
        assert DEFAULT_TEMPLATE["4"]["inputs"]["ckpt_name"] == "{{checkpoint}}"


def test_collect_output_files_skips_temp_previews() -> None:
    entry = {"outputs": {
        "9": {"images": [{"filename": "a.png", "type": "output", "subfolder": ""}]},
        "12": {"images": [{"filename": "p.png", "type": "temp", "subfolder": ""}]},
    }}
    assert [i["filename"] for i in collect_output_files(entry)] == ["a.png"]


def _mock_comfy(monkeypatch, handler) -> None:
    """把传输换成 MockTransport。

    打桩点是模块里的 RetryingClient 而不是 httpx.Client:重试统一在 RetryingClient 里做,
    替换 httpx.Client 既拦不住它(子类在导入期就绑定了真类),也等于把被测的重试逻辑绕过去。
    """
    from app.core import http_retry as ai_retry

    transport = httpx.MockTransport(handler)
    real = ai_retry.RetryingClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    for module in (comfyui, comfyui_client):
        monkeypatch.setattr(module, "RetryingClient", patched, raising=False)


def test_full_flow_discovers_checkpoint_submits_and_downloads(monkeypatch, tmp_path) -> None:
    submitted: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(200, json={"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sd_xl.safetensors"], {}]}}}})
        if path == "/prompt":
            submitted.update(json.loads(request.content))
            return httpx.Response(200, json={"prompt_id": "abc123def"})
        if path == "/history/abc123def":
            return httpx.Response(200, json={"abc123def": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": "openstudio_00001_.png", "subfolder": "", "type": "output"}]}},
            }})
        if path == "/view":
            return httpx.Response(200, content=b"png-bytes")
        return httpx.Response(404)

    _mock_comfy(monkeypatch, handler)
    result = ComfyUIProvider().generate(req(size="832x1216", seed=7), ctx(), tmp_path)

    graph = submitted["prompt"]
    assert graph["4"]["inputs"]["ckpt_name"] == "sd_xl.safetensors", "checkpoint must come from /object_info"
    assert graph["3"]["inputs"]["seed"] == 7
    assert graph["5"]["inputs"] == {"batch_size": 1, "width": 832, "height": 1216}
    assert graph["6"]["inputs"]["text"] == "海边的柴犬"
    assert result.output_paths[0].read_bytes() == b"png-bytes"
    assert result.raw_usage["prompt_id"] == "abc123def"


def test_custom_template_bypasses_checkpoint_discovery(monkeypatch, tmp_path) -> None:
    """A pasted template must be used as-is — no /object_info call it might not survive."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        if request.url.path == "/history/p1":
            return httpx.Response(200, json={"p1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"1": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}},
            }})
        if request.url.path == "/view":
            return httpx.Response(200, content=b"img")
        return httpx.Response(404)

    _mock_comfy(monkeypatch, handler)
    template = json.dumps({"1": {"class_type": "SaveImage", "inputs": {"text": "{{prompt}}"}}})
    ComfyUIProvider().generate(req(), ctx({"workflow_template": template}), tmp_path)
    assert "/object_info/CheckpointLoaderSimple" not in calls


class TestReadableFailures:
    def test_invalid_template_json(self, monkeypatch, tmp_path) -> None:
        _mock_comfy(monkeypatch, lambda r: httpx.Response(404))
        with pytest.raises(ProviderError, match="导出"):
            ComfyUIProvider().generate(req(), ctx({"workflow_template": "not json"}), tmp_path)

    def test_no_checkpoints_installed(self, monkeypatch, tmp_path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [[], {}]}}}})

        _mock_comfy(monkeypatch, handler)
        with pytest.raises(ProviderError, match="checkpoint"):
            ComfyUIProvider().generate(req(), ctx(), tmp_path)

    def test_graph_rejection_surfaces_node_errors(self, monkeypatch, tmp_path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/prompt":
                return httpx.Response(400, json={
                    "error": {"message": "Prompt outputs failed validation"},
                    "node_errors": {"4": {"errors": [{"message": "ckpt_name not in list"}]}},
                }, headers={"content-type": "application/json"})
            return httpx.Response(404)

        _mock_comfy(monkeypatch, handler)
        template = json.dumps({"4": {"class_type": "CheckpointLoaderSimple", "inputs": {}}})
        with pytest.raises(ProviderError, match="ckpt_name not in list"):
            ComfyUIProvider().generate(req(), ctx({"workflow_template": template}), tmp_path)

    def test_server_down_names_the_address(self, monkeypatch, tmp_path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        _mock_comfy(monkeypatch, handler)
        with pytest.raises(ProviderError, match="127.0.0.1:8188"):
            ComfyUIProvider().generate(req(), ctx(), tmp_path)

    def test_execution_error_message_is_extracted(self, monkeypatch, tmp_path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/object_info/CheckpointLoaderSimple":
                return httpx.Response(200, json={"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["m.ckpt"], {}]}}}})
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "p2"})
            if request.url.path == "/history/p2":
                return httpx.Response(200, json={"p2": {"status": {
                    "status_str": "error", "completed": False,
                    "messages": [["execution_error", {"exception_message": "CUDA out of memory"}]],
                }}})
            return httpx.Response(404)

        _mock_comfy(monkeypatch, handler)
        with pytest.raises(ProviderError, match="CUDA out of memory"):
            ComfyUIProvider().generate(req(), ctx(), tmp_path)


# ---------------------------------------------------------------- Phase 2: video + 进度/取消


def vreq(**params) -> GenerationRequest:
    return GenerationRequest(kind="video", model="workflow", prompt="海边延时", parameters=params)


def test_video_kind_is_registered_and_keyless() -> None:
    provider = get_provider("comfyui", "video")
    assert provider is not None
    assert provider.requires_credentials() is False
    assert provider.supports_callbacks is True


def test_video_catalog_entry_exists() -> None:
    assert any(m["id"] == "comfyui:workflow:video" for m in BUILTIN_MODELS)


def test_video_without_template_fails_before_any_submit(monkeypatch, tmp_path) -> None:
    """There is no stock video graph that works everywhere — say so immediately, do not
    submit a graph that will fail later inside ComfyUI."""
    calls: list[str] = []
    _mock_comfy(monkeypatch, lambda r: (calls.append(r.url.path), httpx.Response(404))[1])
    with pytest.raises(ProviderError, match="模板"):
        ComfyUIProvider("video").generate(vreq(), ctx(), tmp_path)
    assert "/prompt" not in calls


def test_video_prefers_the_video_container_output(monkeypatch, tmp_path) -> None:
    """AnimateDiff graphs emit per-frame images AND the combined video — the asset must be
    the video, not frame one."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "v1"})
        if request.url.path == "/history/v1":
            return httpx.Response(200, json={"v1": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {
                    "8": {"images": [{"filename": "frame_00001.png", "subfolder": "", "type": "output"}]},
                    "12": {"gifs": [{"filename": "out.mp4", "subfolder": "video", "type": "output"}]},
                },
            }})
        if request.url.path == "/view":
            return httpx.Response(200, content=b"mp4-bytes")
        return httpx.Response(404)

    _mock_comfy(monkeypatch, handler)
    template = json.dumps({"1": {"class_type": "X", "inputs": {"text": "{{prompt}}", "frames": "{{duration_seconds}}"}}})
    result = ComfyUIProvider("video").generate(vreq(duration_seconds=5), ctx({"workflow_template": template}), tmp_path)
    assert result.output_paths[0].suffix == ".mp4"
    assert result.output_paths[0].read_bytes() == b"mp4-bytes"


class _Callbacks:
    def __init__(self, cancel_after: int = 10**9) -> None:
        self.progress: list[tuple[float, str]] = []
        self._checks = 0
        self._cancel_after = cancel_after

    def on_progress(self, fraction: float, message: str) -> None:
        self.progress.append((fraction, message))

    def is_cancelled(self) -> bool:
        self._checks += 1
        return self._checks > self._cancel_after


def test_progress_is_reported_while_waiting(monkeypatch, tmp_path) -> None:
    from app.ai.providers.contracts.generation import GenerationCallbacks

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(200, json={"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["m.ckpt"], {}]}}}})
        if path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "pg"})
        if path == "/queue":
            return httpx.Response(200, json={"queue_pending": [], "queue_running": []})
        if path == "/history/pg":
            return httpx.Response(200, json={"pg": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}},
            }})
        if path == "/view":
            return httpx.Response(200, content=b"img")
        return httpx.Response(404)

    _mock_comfy(monkeypatch, handler)
    recorder = _Callbacks()
    callbacks = GenerationCallbacks(on_progress=recorder.on_progress, is_cancelled=recorder.is_cancelled)
    ComfyUIProvider("image").generate(req(), ctx(), tmp_path, callbacks=callbacks)
    assert recorder.progress, "at least one progress tick must reach the job"
    assert "ComfyUI" in recorder.progress[0][1]


def test_cancel_interrupts_and_dequeues(monkeypatch, tmp_path) -> None:
    """A user cancel must stop the remote work, not merely abandon the poll loop."""
    from app.ai.providers.contracts.generation import GenerationCallbacks

    stopped: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(200, json={"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["m.ckpt"], {}]}}}})
        if path == "/prompt" and request.method == "POST":
            return httpx.Response(200, json={"prompt_id": "pc"})
        if path in ("/interrupt", "/queue") and request.method == "POST":
            stopped.append((path, request.content))
            return httpx.Response(200, json={})
        if path == "/history/pc":
            return httpx.Response(200, json={})  # 永不完成 —— 取消先到
        return httpx.Response(404)

    _mock_comfy(monkeypatch, handler)
    recorder = _Callbacks(cancel_after=0)  # 第一次检查即已取消
    callbacks = GenerationCallbacks(on_progress=recorder.on_progress, is_cancelled=recorder.is_cancelled)
    with pytest.raises(ProviderError, match="已取消"):
        ComfyUIProvider("image").generate(req(), ctx(), tmp_path, callbacks=callbacks)
    paths = [p for p, _ in stopped]
    assert "/interrupt" in paths, "the running prompt must be interrupted"
    assert any(p == "/queue" and b"pc" in body for p, body in stopped), "a pending prompt must be dequeued"


def test_other_providers_do_not_claim_callbacks() -> None:
    """The runner passes callbacks only where they are understood — a provider that never
    opted in must not advertise support through the shared base class."""
    assert get_provider("openai", "image").supports_callbacks is False
