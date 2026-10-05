#!/usr/bin/env python3
"""The demo ComfyUI behind the documentation captures: the test suite's fake ComfyUI with demo content.

  backend/.venv/bin/python website/scripts/demo-comfyui.py --port 8813 --media /private/path/mosael-demo/media

The seed script (seed-doc-demo.py) starts and stops it like the demo backend and frontend; nobody needs to run it by
hand. It is `backend/tests/fake_comfyui.py` — the HTTP server the ComfyUI plugin's tests talk to, which implements only
the endpoints the plugin uses — loaded with:

- model files with invented, generic names (checkpoints, LoRAs, VAE, text encoder, upscalers). They are entries in a
  listing, not files: each has a size and safetensors header metadata (base model, trigger words, training tags).
  Their previews are Big Buck Bunny frames (CC BY 3.0) that the seed script cuts from the trailer excerpts;
- five workflows (text to image with a checkpoint and LoRAs, image to video, a 4× upscale), saved the way ComfyUI saves
  them, some in folders (`landscapes/`, `video/`, `upscale/`) next to two empty folders (`archive/`, `video/drafts/`),
  so the workflow library's folder tree has depth, counts and empty entries. The image-to-video one uses a node type
  this server does not have (from a fictional node pack known to the fake ComfyUI-Manager) and two model files it does
  not have: one with a huggingface.co download address declared in the workflow, one without. Nothing is ever
  downloaded or generated: the demo only shows these states.

Nothing here touches a real ComfyUI.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

#: Model files: (folder, name, size in bytes, preview frame key or "", safetensors header metadata).
#: The preview frame keys are cut by the seed script into <media>/previews/<key>.jpg.
MODELS: list[tuple[str, str, int, str, dict[str, Any]]] = [
    ("checkpoints", "demo-sdxl-base.safetensors", 6_938_041_004, "meadow",
     {"modelspec.architecture": "stable-diffusion-xl-v1-base", "modelspec.title": "Demo SDXL Base"}),
    ("checkpoints", "demo-sd15-classic.safetensors", 2_132_625_894, "burrow",
     {"modelspec.architecture": "stable-diffusion-v1", "modelspec.title": "Demo SD 1.5 Classic"}),
    ("checkpoints", "demo-flux-dev-fp8.safetensors", 11_901_525_888, "butterfly",
     {"modelspec.architecture": "Flux.1-dev", "modelspec.title": "Demo Flux Dev (fp8)"}),
    ("loras", "storybook-style-lora.safetensors", 228_456_516, "bunny",
     {"ss_base_model_version": "sdxl_base_v1-0", "ss_output_name": "storybook-style",
      "modelspec.trigger_phrase": "storybook style, soft watercolor",
      "ss_network_dim": "32", "ss_network_alpha": "16", "ss_num_epochs": "10", "ss_resolution": "(1024, 1024)",
      "ss_tag_frequency": json.dumps({"10_storybook": {"storybook style": 48, "soft watercolor": 41, "rabbit": 22,
                                                       "forest": 18, "meadow": 12, "picture book": 9}})}),
    ("loras", "forest-light-lora.safetensors", 151_112_304, "forest",
     {"ss_base_model_version": "sdxl_base_v1-0", "ss_output_name": "forest-light",
      "ss_network_dim": "16", "ss_network_alpha": "8", "ss_num_epochs": "12",
      "ss_tag_frequency": json.dumps({"8_light": {"forest light": 36, "god rays": 30, "morning mist": 21, "tree": 17,
                                                  "backlit": 11}})}),
    ("loras", "big-bunny-character-lora.safetensors", 75_613_740, "closeup",
     {"ss_base_model_version": "sd_v1", "ss_output_name": "big-bunny-character",
      "modelspec.trigger_phrase": "bigbuck, grey rabbit",
      "ss_network_dim": "32", "ss_network_alpha": "32", "ss_num_epochs": "8",
      "ss_tag_frequency": json.dumps({"12_bigbuck": {"bigbuck": 60, "grey rabbit": 52, "long ears": 30, "smile": 14}})}),
    ("loras", "film-grain-flux-lora.safetensors", 171_970_032, "ambush",
     {"ss_base_model_version": "flux1", "ss_output_name": "film-grain-flux",
      "modelspec.trigger_phrase": "film grain", "ss_network_dim": "16", "ss_num_epochs": "6"}),
    ("vae", "demo-sdxl-vae.safetensors", 334_641_164, "",
     {"modelspec.architecture": "stable-diffusion-xl-v1-base/vae"}),
    ("vae", "demo-video-vae.safetensors", 253_815_318, "", {}),
    ("text_encoders", "demo-video-text-encoder.safetensors", 6_735_906_816, "", {}),
    ("upscale_models", "demo-upscale-4x.pth", 66_961_958, "", {}),
    ("upscale_models", "demo-upscale-2x.pth", 67_040_989, "", {}),
]

#: The node pack the fake ComfyUI-Manager knows for the one missing node type (fictional).
NODE_PACK = ("comfyui-frame-tools", "Frame Tools", ["FrameInterpolate", "FrameBlend"])

#: Declared in the image-to-video workflow, missing on the server: shown, never downloaded.
MISSING_DOWNLOAD_URL = "https://huggingface.co/example-org/demo-video/resolve/main/demo-video-i2v-480p.safetensors"


def _folder(name: str) -> list[str]:
    return [model[1] for model in MODELS if model[0] == name]


# ------------------------------------------------------------------------------------------------ workflows


class UiGraph:
    """A workflow in ComfyUI's own save format (nodes with positions, a links table), built node by node."""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.links: list[list[Any]] = []

    def node(self, node_id: int, kind: str, pos: tuple[int, int], size: tuple[int, int], widgets: list[str] = (),
             values: list[Any] = (), inputs: list[str] = (), title: str = "", models: list[dict[str, str]] = ()) -> int:
        entry: dict[str, Any] = {
            "id": node_id, "type": kind, "pos": list(pos), "size": list(size), "flags": {}, "order": len(self.nodes),
            "mode": 0, "inputs": [{"name": name, "link": None} for name in inputs]
                              + [{"name": name, "widget": {"name": name}, "link": None} for name in widgets],
            "outputs": [], "properties": {"Node name for S&R": kind}, "widgets_values": list(values),
        }
        if title:
            entry["title"] = title
        if models:
            entry["properties"]["models"] = list(models)
        self.nodes.append(entry)
        return node_id

    def link(self, source: int, slot: int, target: int, name: str, kind: str) -> None:
        link_id = len(self.links) + 1
        node = next(one for one in self.nodes if one["id"] == target)
        entry = next(one for one in node["inputs"] if one["name"] == name)
        entry["link"] = link_id
        self.links.append([link_id, source, slot, target, list(node["inputs"]).index(entry), kind])

    def saved(self, graph_id: str) -> dict[str, Any]:
        return {"id": graph_id, "revision": 0, "last_node_id": max(one["id"] for one in self.nodes),
                "last_link_id": len(self.links), "nodes": self.nodes, "links": self.links, "groups": [], "config": {},
                "extra": {"ds": {"scale": 0.8, "offset": [0, 0]}}, "version": 0.4}


SAMPLER = ["seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise"]
SAMPLER_IN = ["model", "positive", "negative", "latent_image"]


def storybook_portrait() -> dict[str, Any]:
    """Text to image: SDXL checkpoint → storybook LoRA → prompts → sampler → save."""
    g = UiGraph()
    g.node(4, "CheckpointLoaderSimple", (40, 260), (315, 98), ["ckpt_name"], ["demo-sdxl-base.safetensors"])
    g.node(10, "LoraLoader", (400, 260), (315, 126), ["lora_name", "strength_model", "strength_clip"],
           ["storybook-style-lora.safetensors", 0.8, 0.8], ["model", "clip"])
    g.node(6, "CLIPTextEncode", (760, 80), (400, 180), ["text"],
           ["storybook style, soft watercolor, a big friendly rabbit sitting in a sunny forest meadow"], ["clip"],
           title="Prompt")
    g.node(7, "CLIPTextEncode", (760, 300), (400, 140), ["text"], ["blurry, low quality, text"], ["clip"],
           title="Negative prompt")
    g.node(5, "EmptyLatentImage", (760, 480), (315, 106), ["width", "height", "batch_size"], [832, 1216, 1])
    g.node(3, "KSampler", (1200, 180), (315, 262), SAMPLER, [42, "randomize", 28, 6.5, "dpmpp_2m", "karras", 1.0],
           SAMPLER_IN)
    g.node(8, "VAEDecode", (1560, 180), (210, 46), [], [], ["samples", "vae"])
    g.node(9, "SaveImage", (1810, 180), (315, 270), ["filename_prefix"], ["storybook"], ["images"])
    g.link(4, 0, 10, "model", "MODEL")
    g.link(4, 1, 10, "clip", "CLIP")
    g.link(10, 1, 6, "clip", "CLIP")
    g.link(10, 1, 7, "clip", "CLIP")
    g.link(10, 0, 3, "model", "MODEL")
    g.link(6, 0, 3, "positive", "CONDITIONING")
    g.link(7, 0, 3, "negative", "CONDITIONING")
    g.link(5, 0, 3, "latent_image", "LATENT")
    g.link(3, 0, 8, "samples", "LATENT")
    g.link(4, 2, 8, "vae", "VAE")
    g.link(8, 0, 9, "images", "IMAGE")
    return g.saved("6c0e1f5a-41d2-4e8b-9a37-1d2f3b4c5a60")


def watercolor_character() -> dict[str, Any]:
    """Text to image on SD 1.5 with a character LoRA."""
    g = UiGraph()
    g.node(4, "CheckpointLoaderSimple", (40, 240), (315, 98), ["ckpt_name"], ["demo-sd15-classic.safetensors"])
    g.node(10, "LoraLoader", (400, 240), (315, 126), ["lora_name", "strength_model", "strength_clip"],
           ["big-bunny-character-lora.safetensors", 1.0, 1.0], ["model", "clip"], title="Character LoRA")
    g.node(6, "CLIPTextEncode", (760, 60), (400, 180), ["text"],
           ["bigbuck, grey rabbit, standing by a burrow under a tree, watercolor illustration"], ["clip"], title="Prompt")
    g.node(7, "CLIPTextEncode", (760, 280), (400, 140), ["text"], ["blurry, extra limbs"], ["clip"],
           title="Negative prompt")
    g.node(5, "EmptyLatentImage", (760, 460), (315, 106), ["width", "height", "batch_size"], [512, 768, 2])
    g.node(3, "KSampler", (1200, 160), (315, 262), SAMPLER, [7, "randomize", 25, 7.0, "euler", "normal", 1.0], SAMPLER_IN)
    g.node(8, "VAEDecode", (1560, 160), (210, 46), [], [], ["samples", "vae"])
    g.node(9, "SaveImage", (1810, 160), (315, 270), ["filename_prefix"], ["character"], ["images"])
    for source, slot, target, name, kind in [
        (4, 0, 10, "model", "MODEL"), (4, 1, 10, "clip", "CLIP"), (10, 1, 6, "clip", "CLIP"), (10, 1, 7, "clip", "CLIP"),
        (10, 0, 3, "model", "MODEL"), (6, 0, 3, "positive", "CONDITIONING"), (7, 0, 3, "negative", "CONDITIONING"),
        (5, 0, 3, "latent_image", "LATENT"), (3, 0, 8, "samples", "LATENT"), (4, 2, 8, "vae", "VAE"),
        (8, 0, 9, "images", "IMAGE"),
    ]:
        g.link(source, slot, target, name, kind)
    return g.saved("0b7d4e2c-93a1-4f6e-8c05-7e6a5d4c3b21")


def bunny_image_to_video() -> dict[str, Any]:
    """Image to video. Two model files this server lacks (one with a declared huggingface.co address) and one node type
    it lacks (FrameInterpolate, from the fictional node pack)."""
    g = UiGraph()
    g.node(37, "UNETLoader", (40, 40), (315, 82), ["unet_name", "weight_dtype"],
           ["demo-video-i2v-480p.safetensors", "default"], title="Video model",
           models=[{"name": "demo-video-i2v-480p.safetensors", "directory": "diffusion_models",
                    "url": MISSING_DOWNLOAD_URL}])
    g.node(38, "CLIPLoader", (40, 180), (315, 82), ["clip_name", "type"], ["demo-video-umt5.safetensors", "wan"],
           title="Text encoder")
    g.node(39, "VAELoader", (40, 320), (315, 58), ["vae_name"], ["demo-video-vae.safetensors"])
    g.node(52, "LoadImage", (40, 440), (315, 314), ["image"], ["bunny-start-frame.png", "image"],
           title="Start frame")
    g.node(6, "CLIPTextEncode", (420, 40), (400, 160), ["text"],
           ["the big rabbit stretches and yawns in the morning sun, gentle camera push-in"], ["clip"], title="Prompt")
    g.node(7, "CLIPTextEncode", (420, 240), (400, 120), ["text"], ["static, blurry, distorted"], ["clip"],
           title="Negative prompt")
    g.node(50, "WanImageToVideo", (880, 200), (315, 210), ["width", "height", "length", "batch_size"], [832, 480, 81, 1],
           ["positive", "negative", "vae", "start_image"])
    g.node(3, "KSampler", (1240, 120), (315, 262), SAMPLER, [11, "randomize", 20, 5.0, "euler", "normal", 1.0], SAMPLER_IN)
    g.node(8, "VAEDecode", (1600, 120), (210, 46), [], [], ["samples", "vae"])
    g.node(60, "FrameInterpolate", (1600, 240), (315, 82), ["multiplier"], [2], ["images"], title="Smooth motion")
    g.node(61, "CreateVideo", (1960, 120), (270, 78), ["fps"], [32], ["images"])
    g.node(62, "SaveVideo", (2270, 120), (315, 280), ["filename_prefix", "format", "codec"],
           ["video/bunny", "auto", "auto"], ["video"])
    for source, slot, target, name, kind in [
        (38, 0, 6, "clip", "CLIP"), (38, 0, 7, "clip", "CLIP"), (6, 0, 50, "positive", "CONDITIONING"),
        (7, 0, 50, "negative", "CONDITIONING"), (39, 0, 50, "vae", "VAE"), (52, 0, 50, "start_image", "IMAGE"),
        (37, 0, 3, "model", "MODEL"), (50, 0, 3, "positive", "CONDITIONING"), (50, 1, 3, "negative", "CONDITIONING"),
        (50, 2, 3, "latent_image", "LATENT"), (3, 0, 8, "samples", "LATENT"), (39, 0, 8, "vae", "VAE"),
        (8, 0, 60, "images", "IMAGE"), (60, 0, 61, "images", "IMAGE"), (61, 0, 62, "video", "VIDEO"),
    ]:
        g.link(source, slot, target, name, kind)
    return g.saved("a41f9c3e-27b8-4d10-b6e5-3c9d8e7f6a52")


#: Exported with ComfyUI's "Export (API)": no layout (the plugin lays it out), saved into workflows/ all the same.
FOREST_LANDSCAPE_API: dict[str, Any] = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "demo-sdxl-base.safetensors"}},
    "10": {"class_type": "LoraLoader", "inputs": {"lora_name": "forest-light-lora.safetensors", "strength_model": 0.7,
                                                   "strength_clip": 0.7, "model": ["4", 0], "clip": ["4", 1]}},
    "11": {"class_type": "VAELoader", "inputs": {"vae_name": "demo-sdxl-vae.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "forest light, god rays, a quiet clearing at dawn",
                                                      "clip": ["10", 1]}, "_meta": {"title": "Prompt"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "people, text, watermark", "clip": ["10", 1]},
          "_meta": {"title": "Negative prompt"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1344, "height": 768, "batch_size": 1}},
    "3": {"class_type": "KSampler", "inputs": {"seed": 3, "steps": 30, "cfg": 6.0, "sampler_name": "dpmpp_2m",
                                                "scheduler": "karras", "denoise": 1.0, "model": ["10", 0],
                                                "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["11", 0]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "landscape"}},
}

UPSCALE_API: dict[str, Any] = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "still.png"}, "_meta": {"title": "Image to upscale"}},
    "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "demo-upscale-4x.pth"}},
    "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
    "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "upscaled"}},
}


def workflows() -> dict[str, Any]:
    return {
        "storybook-portrait.json": storybook_portrait(),
        "watercolor-character.json": watercolor_character(),
        "landscapes/forest-light-landscape.json": FOREST_LANDSCAPE_API,
        "video/bunny-image-to-video.json": bunny_image_to_video(),
        "upscale/upscale-4x.json": UPSCALE_API,
    }


#: Empty folders in workflows/ (relative to the user directory), the way the workflow library's "New folder" leaves them.
EMPTY_FOLDERS = {"workflows/archive", "workflows/video/drafts"}


#: Pasted into the workflow library's import dialog in the recordings (API format, recognized on the spot).
IMPORT_SAMPLE = json.dumps({
    "1": {"class_type": "LoadImage", "inputs": {"image": "frame.png"}},
    "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "demo-upscale-8x.pth"}},
    "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
    "4": {"class_type": "FrameBlend", "inputs": {"images": ["3", 0], "amount": 0.5}},
    "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "upscaled"}},
}, separators=(",", ":"))


# ------------------------------------------------------------------------------------------------ server


def object_info(base: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
    """The fake's node definitions, with the model pickers listing the demo files (ComfyUI fills those dropdowns from
    the model folders)."""
    info = copy.deepcopy(base)
    for name in ("CreateVideo", "SaveVideo", "UNETLoader", "CLIPLoader", "VAELoader"):
        info[name] = copy.deepcopy(video[name])
    info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [_folder("checkpoints")]
    info["LoraLoader"]["input"]["required"]["lora_name"] = [_folder("loras")]
    info["VAELoader"]["input"]["required"]["vae_name"] = [_folder("vae")]
    info["UNETLoader"]["input"]["required"]["unet_name"] = [_folder("diffusion_models")]
    info["CLIPLoader"]["input"]["required"]["clip_name"] = [_folder("text_encoders")]
    info["CLIPLoader"]["input"]["required"]["type"] = [["wan", "stable_diffusion", "flux"]]
    info["UpscaleModelLoader"]["input"]["required"]["model_name"] = [_folder("upscale_models")]
    for name in ("CheckpointLoaderSimple", "LoraLoader", "VAELoader", "UNETLoader", "CLIPLoader", "UpscaleModelLoader"):
        info[name]["output_node"] = False
    info["WanImageToVideo"]["output"] = ["CONDITIONING", "CONDITIONING", "LATENT"]
    return info


def build(media: Path):
    sys.path.insert(0, str(ROOT / "backend/tests"))
    import fake_comfyui as fake  # noqa: E402 — the test suite's fake ComfyUI, stdlib only

    previews: dict[str, bytes] = {}
    for folder, name, _size, frame, _meta in MODELS:
        if frame:
            previews[f"{folder}/{name}"] = (media / "previews" / f"{frame}.jpg").read_bytes()
    #: Modification times in the recent past (the fake lists workflows as 1 ms after 1970 and models in November 2023).
    saved_at = {path: int((time.time() - 3600 * (6 + 30 * index)) * 1000) for index, path in enumerate(workflows())}
    changed = {f"{model[0]}/{model[1]}": time.time() - 86400 * (2 + 5 * index) for index, model in enumerate(MODELS)}

    class Handler(fake._Handler):
        def do_GET(self) -> None:  # noqa: N802
            from urllib.parse import unquote

            path = self.path.split("?", 1)[0]
            prefix = "/experiment/models/preview/"
            state = self.server.state
            folder = unquote(path[len("/experiment/models/"):]) if path.startswith("/experiment/models/") else ""
            if folder in state.model_folders:
                self._json([{"name": name, "pathIndex": 0, "modified": changed.get(f"{folder}/{name}", time.time()),
                             "created": changed.get(f"{folder}/{name}", time.time()),
                             "size": state.model_sizes.get(f"{folder}/{name}", 1000)}
                            for name in state.model_folders[folder]])
                return
            if path.startswith(prefix):
                folder, _index, name = unquote(path[len(prefix):]).split("/", 2)
                body = previews.get(f"{folder}/{name}")
                if body is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            if path == "/api/userdata" and "dir=workflows" in self.path and self.server.state.workflows:
                # Written since the demo started (an app form saved through Mosael, an import): the fake's own time
                written = self.server.state.workflow_modified
                self._json([{"path": name, "size": len(json.dumps(graph)),
                             "modified": written.get(name) or saved_at.get(name, int(time.time() * 1000))}
                            for name, graph in self.server.state.workflows.items()])
                return
            super().do_GET()

    class DemoComfyUI(fake.ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self, port: int) -> None:
            super().__init__(("127.0.0.1", port), Handler)
            state = fake.State()
            state.workflows = workflows()
            state.dirs = set(EMPTY_FOLDERS)
            state.object_info = object_info(fake.OBJECT_INFO, fake.VIDEO_NODE_INFO)
            state.model_folders = {folder: _folder(folder) for folder in dict.fromkeys(m[0] for m in MODELS)}
            state.model_folders["diffusion_models"] = []
            state.model_sizes = {f"{folder}/{name}": size for folder, name, size, _frame, _meta in MODELS}
            state.model_metadata = {f"{folder}/{name}": meta for folder, name, _size, _frame, meta in MODELS if meta}
            state.model_previews = set(previews)
            state.manager = "V4.2.1"
            pack, title, nodes = NODE_PACK
            state.manager_mappings = {pack: [nodes, {"title_aux": title}]}
            self.state = state

    return DemoComfyUI


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--media", type=Path, required=True, help="the seed's media directory (holds previews/)")
    args = parser.parse_args()
    server = build(args.media)(args.port)
    print(f"Demo ComfyUI on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
