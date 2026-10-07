"""「这个工作流有什么问题」(ADR 0042 §3):一份界面格式的图进去,出一张按节点列的问题单,每条带严重程度、原因、改法。

    {"op": "check_graph", "content": 界面格式的图, "error"?: 上一次运行的报错原文(任务的 job.error)}

查的是 ComfyUI **真会跑**的那张:先照前端的规矩把界面格式转成 API 图(convert.to_api —— 子图展开、提升出来的控件取外面
那个节点上的值、旁路和静音的不算、Reroute / Get / Set 顺着走到真正的上游),再一个节点一个节点对着这台 ComfyUI 的节点定义
(只问图里那几类,node_catalog.classes)看:

- 缺的节点类型(`missing_type`)—— 和缺失项同一套(workflow_import / workflow_library 的认法),带上哪个节点包能补;
- 缺的模型(`missing_model`)—— 选模型文件的那一格,值不在这台机器那个加载节点的下拉里;同名文件在别的子目录里就说改成哪个,
  图里声明了下载地址就带上;
- 连线类型对不上(`link_type_mismatch`)、必填的插口没连(`unconnected_required`)、下拉值不在列表里(`combo_not_in_list`)、
  读素材的那一格(LoadImage 的 image……)要的文件不在 input 目录里(`missing_input_file`)、数值超出范围(`number_out_of_range`)
  —— 这几样 ComfyUI 要等提交时才报,这里提前说;新式节点(V3)的三种特殊输入(跟着连进来的类型走的、一组能往下长的插口、
  选了哪一项再多出几格的下拉)照它们自己的规矩看;
- 宽高不是那一格要求的倍数(`size_not_multiple`,看节点定义里的 `step`:潜空间按 8、视频按 16……不整除会被向下取整);
- 加载的大模型和接在它上面的 LoRA、和 ControlNet 底模家族对不上(`family_mismatch`,用模型库认家族的那一套,见
  library.known_families;同一家的几支 —— SDXL 上的 Pony、Illustrious —— 不算对不上);
- 给了上一次运行的报错:拆到具体节点(`last_run_error`)—— `#12` / `#12:5` 这种写法(ComfyUI 校验错误、Mosael 提交前的
  检查)、「Model in folder … not found」、执行失败时报的节点类型(graph.execution_error_parts 拆出来的那一种写法)。

节点用 canvas 的写法指(`12`、子图里的 `12:5`),工作台的「定位」认它。子图里的问题带上「在子图『…』里」。
"""

from __future__ import annotations

import re
from typing import Any

import canvas
import convert
import labels
import library
import node_catalog
from comfy_http import Comfy
from families import BRANCHES
from lines import ComfyError, say
from workflow_import import _type_of
from workflow_library import VIRTUAL_NODES, _choices, _packs, live_graph

#: 报错原文最多读多少字(ComfyUI 的「Value not in list」带着整张可选值列表)。
MAX_ERROR = 20000
#: 问题单最多多少条。
MAX_FINDINGS = 200
#: 看着像模型文件的值(选模型的那一格不在 labels 的表里时,按这个认)。
MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft", ".onnx")
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
#: 底模家族那一层(SDXL 上的几支、Wan 的两代、Flux 的变体)→ 那一层本身:同一层里的不算对不上。
_FAMILY_ROOT = {branch: root for root, branches in BRANCHES.items() for branch in branches}
#: 大模型从哪一格读、LoRA / ControlNet 从哪一格读(和 labels 的模型目录一致)。
_BASE_INPUTS = {"ckpt_name": "checkpoints", "unet_name": "diffusion_models"}
_ADDON_INPUTS = {"lora_name": "loras", "control_net_name": "controlnet"}
#: 报错里指节点的写法:`#12`、子图里的 `#12:5`。
_NODE_MENTION = re.compile(r"#(\d+(?::\d+)*)\b")
_MISSING_FILE = re.compile(r"Model in folder '([^']+)' with filename '([^']+)' not found", re.IGNORECASE)
#: 执行失败的那一句(run.failure 的两种语言,和 ComfyUI 原样的 node_type: message)
_EXECUTION_FAILED = re.compile(r"(?:ComfyUI 执行失败|ComfyUI execution failed)[::]\s*([^:\s][^:]*?):\s*(.+)", re.IGNORECASE)


#: ComfyUI 新式节点(V3)的三种特殊输入:跟着连进来的类型走的(`MATCHTYPE`,模板里写着能收哪几种)、能一格格往下长的一组插口
#: (`AUTOGROW`,API 图里是 `images.image_1`、`images.image_2`……)、选了哪一项再多出几格的下拉(`DYNAMICCOMBO`,值是选项的 key)。
V3_MATCH, V3_GROW, V3_COMBO = "COMFY_MATCHTYPE_V3", "COMFY_AUTOGROW_V3", "COMFY_DYNAMICCOMBO_V3"
#: 读素材的那几种上传控件(LoadImage 的 image……):值是 input 目录里的文件名
_UPLOADS = ("image_upload", "video_upload", "audio_upload", "animated_image_upload")


def _is_link(value: Any, api: dict[str, Any]) -> bool:
    return isinstance(value, list) and len(value) == 2 and str(value[0]) in api and isinstance(value[1], int)


def _definitions(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    declared = spec.get("input") if isinstance(spec.get("input"), dict) else {}
    required = declared.get("required") if isinstance(declared.get("required"), dict) else {}
    optional = declared.get("optional") if isinstance(declared.get("optional"), dict) else {}
    return required, optional


def _options(definition: Any) -> dict[str, Any]:
    return definition[1] if isinstance(definition, list) and len(definition) > 1 and isinstance(definition[1], dict) else {}


def _is_socket(definition: Any) -> bool:
    """只能接线的插口(MODEL、IMAGE……),不是 widget(和 graph._is_socket 同一个判法)。"""
    if not isinstance(definition, list) or not definition:
        return False
    options = _options(definition)
    if options.get("forceInput"):
        return True
    kind = options.get("widgetType") or definition[0]
    return not (isinstance(kind, list) or kind in convert.WIDGET_TYPES)


def _output_type(spec: dict[str, Any], slot: int) -> Any:
    outputs = spec.get("output") if isinstance(spec.get("output"), list) else []
    if slot >= len(outputs):
        return None
    kind = outputs[slot]
    return "COMBO" if isinstance(kind, list) else "*" if kind == V3_MATCH else kind


def _input_type(definition: Any) -> str:
    """这一格收什么类型。跟着连进来的走的(V3 的 MATCHTYPE)按模板里写的那几种,没写就是什么都收。"""
    kind = _type_of(definition)
    if kind == V3_MATCH:
        allowed = (_options(definition).get("template") or {}).get("allowed_types")
        return str(allowed) if isinstance(allowed, str) and allowed.strip() else "*"
    return kind


def _norm(value: Any) -> str:
    return str(value).replace("\\", "/")


def _looks_like_model(name: str, value: Any) -> bool:
    return isinstance(value, str) and (name.endswith("_name") or name == "upscale_model") and value.lower().endswith(MODEL_SUFFIXES)


class _Findings:
    """问题单:按节点记,同一个节点同一格同一种只记一次。"""

    def __init__(self, content: dict[str, Any], api: dict[str, Any], object_info: dict[str, Any], locale: str) -> None:
        self.content = content
        self.api = api
        self.object_info = object_info
        self.locale = locale
        self.items: list[dict[str, Any]] = []
        self.seen: set[tuple[str, str, str]] = set()
        self.paths = canvas.instance_paths(content)

    def add(self, ref: str, kind: str, severity: str, cause: str, fix: str, *, input_name: str = "",
            class_type: str = "", refs: list[str] | None = None) -> None:
        key = (ref, kind, input_name)
        if key in self.seen or len(self.items) >= MAX_FINDINGS:
            return
        self.seen.add(key)
        node = self.api.get(ref) or {}
        layer, raw = canvas.locate_ref(self.content, ref) if ref else (None, None)
        title = str(((node.get("_meta") or {}).get("title")) or (raw or {}).get("title") or "")
        entry: dict[str, Any] = {
            "ref": ref, "type": class_type or str(node.get("class_type") or (raw or {}).get("type") or ""),
            "severity": severity, "kind": kind, "cause": cause, "fix": fix,
        }
        if title and title != entry["type"]:
            entry["title"] = title[:200]
        if input_name:
            entry["input"] = input_name
        if layer is not None:
            entry["subgraph"] = {"id": str(layer.get("id")), "name": str(layer.get("name") or layer.get("id"))[:200],
                                 "instances": self.paths.get(str(layer.get("id")), [])}
        if refs and len(refs) > 1:
            entry["refs"] = refs[:20]
        self.items.append(entry)

    def say(self, zh: str, en: str) -> str:
        return str(say(self.locale, zh, en))


def _declared_downloads(content: dict[str, Any]) -> dict[str, dict[str, str]]:
    """图里节点上声明的模型下载地址(`properties.models`,模板都带):文件名 → {url, directory}。"""
    found: dict[str, dict[str, str]] = {}
    for scope in [content, *canvas.definitions(content).values()]:
        for node in canvas.nodes_of(scope):
            for one in ((node.get("properties") or {}).get("models") or []):
                if isinstance(one, dict) and isinstance(one.get("name"), str) and isinstance(one.get("url"), str):
                    found.setdefault(_norm(one["name"]).split("/")[-1],
                                     {"url": one["url"], "directory": str(one.get("directory") or "")})
    return found


def _missing_types(found: _Findings, object_info: dict[str, Any], comfy: Comfy) -> None:
    by_type: dict[str, list[str]] = {}
    for ref, node in found.api.items():
        kind = str(node.get("class_type") or "")
        if kind and kind not in object_info and kind not in VIRTUAL_NODES:
            by_type.setdefault(kind, []).append(ref)
    if not by_type:
        return
    try:
        packs = _packs(comfy, sorted(by_type))
    except ComfyError:
        packs = {}
    for kind, refs in sorted(by_type.items()):
        offered = packs.get(kind) or []
        if offered:
            names = "、".join(one["title"] + ("(已装,可能没启用或要重启)" if one.get("installed") else "") for one in offered[:3])
            names_en = ", ".join(one["title"] + (" (installed: maybe disabled or needs a restart)" if one.get("installed") else "")
                                 for one in offered[:3])
            fix = found.say(f"装上提供它的节点包:{names}(comfy_node_pack_info 先看看再装)",
                            f"Install the node pack that provides it: {names_en} (check it with comfy_node_pack_info first)")
        else:
            fix = found.say("这台 ComfyUI 上没有这个节点类型,也查不到哪个节点包提供它:用 comfy_node_pack_search 按名字找",
                            "This ComfyUI lacks this node type and no known pack provides it: search with comfy_node_pack_search")
        found.add(refs[0], "missing_type", "error",
                  found.say(f"这台 ComfyUI 没有节点类型「{kind}」({len(refs)} 处)", f"This ComfyUI has no node type “{kind}” ({len(refs)} place(s))"),
                  fix, class_type=kind, refs=refs)


def _value_findings(found: _Findings, ref: str, node: dict[str, Any], spec: dict[str, Any],
                    downloads: dict[str, dict[str, str]]) -> None:
    kind = str(node.get("class_type") or "")
    required, optional = _definitions(spec)
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    for name, definition in required.items():
        kind_of_input = _type_of(definition)
        if kind_of_input == V3_COMBO or not (_is_socket(definition) or kind_of_input == V3_MATCH):
            continue
        present = name in inputs or (kind_of_input == V3_GROW and any(key.startswith(f"{name}.") for key in inputs))
        if not present:
            shown = _input_type(definition) if kind_of_input != V3_GROW else name
            upstream = _cut_upstream(found, ref, name)
            cause = (found.say(f"必填的输入「{name}」({shown})接着的 #{upstream} 被静音 / 旁路后接不上了,等于没连",
                               f"Required input “{name}” ({shown}) is wired to #{upstream}, which is muted / bypassed away, so it is effectively unconnected")
                     if upstream else
                     found.say(f"必填的输入「{name}」({shown})没连上", f"Required input “{name}” ({shown}) is not connected"))
            fix = (found.say(f"把 #{upstream} 打开(取消静音 / 旁路),或者给「{name}」另接一个 {shown} 的输出",
                             f"Un-mute / un-bypass #{upstream}, or connect another {shown} output to “{name}”")
                   if upstream else found.say(f"给它接一个 {shown} 的输出", f"Connect an output of type {shown} to it"))
            found.add(ref, "unconnected_required", "error", cause, fix, input_name=name)
    for name, value in inputs.items():
        definition = required.get(name, optional.get(name))
        if definition is None:
            continue
        wanted = _input_type(definition)
        if _is_link(value, found.api):
            origin = found.api[str(value[0])]
            origin_spec = found.object_info.get(str(origin.get("class_type") or ""))
            if not isinstance(origin_spec, dict):
                continue
            given = _output_type(origin_spec, value[1])
            if given is None or (wanted == "COMBO" and given in ("COMBO", "*")):
                continue
            if not convert.connectable(given, wanted):
                found.add(ref, "link_type_mismatch", "error",
                          found.say(f"「{name}」要 {wanted},接进来的是 #{value[0]} 的 {given}",
                                    f"“{name}” expects {wanted} but gets {given} from #{value[0]}"),
                          found.say(f"换一个输出 {wanted} 的节点接到「{name}」", f"Connect a node that outputs {wanted} to “{name}”"),
                          input_name=name)
            continue
        if isinstance(value, dict) and set(value) == {"__value__"}:
            value = value["__value__"]
        options = _options(definition)
        if wanted == V3_COMBO:
            keys = [str(one.get("key")) for one in options.get("options") or [] if isinstance(one, dict) and one.get("key") is not None]
            if isinstance(value, str) and keys and value not in keys:
                _choice_finding(found, ref, kind, name, value, keys, downloads)
            continue
        choices = _choices(definition)
        if choices is not None:
            names = [_norm(one) for one in choices if isinstance(one, str)]
            if isinstance(value, str) and _norm(value) not in names and value not in choices:
                if any(options.get(flag) for flag in _UPLOADS):
                    found.add(ref, "missing_input_file", "error",
                              found.say(f"「{name}」要的文件「{value}」不在这台 ComfyUI 的 input 目录里",
                                        f"The file “{value}” for “{name}” is not in this ComfyUI's input folder"),
                              found.say("在这个节点上传一个文件(模板里的示例图要自己放进 input),或者换成已有的",
                                        "Upload a file on this node (template sample images must be put into input yourself), or pick an existing one"),
                              input_name=name)
                else:
                    _choice_finding(found, ref, kind, name, value, names, downloads)
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            low, high = options.get("min"), options.get("max")
            if (isinstance(low, (int, float)) and value < low) or (isinstance(high, (int, float)) and value > high):
                found.add(ref, "number_out_of_range", "error",
                          found.say(f"「{name}」= {value},超出了 {low} ~ {high}", f"“{name}” = {value} is outside {low} to {high}"),
                          found.say(f"改成 {low} 到 {high} 之间的数", f"Set it between {low} and {high}"), input_name=name)
            step = options.get("step")
            if name in ("width", "height") and isinstance(step, int) and step >= 8 and isinstance(value, int) and value % step:
                snapped = value - value % step
                found.add(ref, "size_not_multiple", "warning",
                          found.say(f"「{name}」= {value} 不是 {step} 的倍数,跑的时候会被取整成 {snapped}",
                                    f"“{name}” = {value} is not a multiple of {step}; it will be floored to {snapped}"),
                          found.say(f"改成 {step} 的倍数(比如 {snapped} 或 {snapped + step})",
                                    f"Use a multiple of {step} (e.g. {snapped} or {snapped + step})"), input_name=name)


def _cut_upstream(found: _Findings, ref: str, name: str) -> str:
    """界面上这一格其实连着线、只是上游被静音 / 旁路了(转成 API 图时线断了):回上游节点的写法;真没连回空串。"""
    layer, raw = canvas.locate_ref(found.content, ref)
    if raw is None:
        return ""
    entry = next((one for one in raw.get("inputs") or [] if isinstance(one, dict) and one.get("name") == name), None)
    if entry is None or entry.get("link") is None:
        return ""
    scope = layer if layer is not None else found.content
    link = canvas._links(scope).get(str(entry["link"]))  # noqa: SLF001 — 同一个插件
    if link is None:
        return ""
    prefix = ref.rsplit(":", 1)[0] + ":" if ":" in ref else ""
    return f"{prefix}{link[0]}"


def _choice_finding(found: _Findings, ref: str, kind: str, name: str, value: str, names: list[str],
                    downloads: dict[str, dict[str, str]]) -> None:
    base = _norm(value).split("/")[-1]
    if labels.model_folder(kind, name) or _looks_like_model(name, value):
        folder = labels.model_folder(kind, name) or (downloads.get(base) or {}).get("directory", "")
        elsewhere = next((one for one in names if one.split("/")[-1] == base), "")
        if elsewhere:
            fix = found.say(f"这台机器上有同一个文件,在「{elsewhere}」:把这一格改成它",
                            f"This machine has the same file as “{elsewhere}”: pick that one")
        elif base in downloads:
            fix = found.say(f"下载它到 {folder or '对应的模型目录'}:{downloads[base]['url']}(先说多大,确认后再下)",
                            f"Download it into {folder or 'the matching models folder'}: {downloads[base]['url']} (state the size and confirm first)")
        else:
            fix = found.say(f"放一个文件进 {folder or '对应的模型目录'},或者在下拉里换成已有的(共 {len(names)} 个)",
                            f"Put the file into {folder or 'the matching models folder'}, or pick one of the {len(names)} available")
        found.add(ref, "missing_model", "error",
                  found.say(f"这台机器上没有模型文件「{value}」({folder or name})", f"This machine doesn't have the model file “{value}” ({folder or name})"),
                  fix, input_name=name)
        return
    close = [one for one in names if one.lower() == value.lower()] or names[:5]
    found.add(ref, "combo_not_in_list", "error",
              found.say(f"「{name}」= {value!r} 不在可选的值里", f"“{name}” = {value!r} is not one of the allowed values"),
              found.say(f"换成列表里的一个,比如 {'、'.join(close)}", f"Pick one of the allowed values, e.g. {', '.join(close)}"),
              input_name=name)


def _base_of(found: _Findings, ref: str, depth: int = 0) -> str | None:
    """顺着 `model` 输入往上找到读大模型的那个节点(LoRA 一个接一个串着的也走过去)。"""
    node = found.api.get(ref) or {}
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    if any(isinstance(inputs.get(name), str) for name in _BASE_INPUTS):
        return ref
    upstream = inputs.get("model")
    if depth > 32 or not _is_link(upstream, found.api):
        return None
    return _base_of(found, str(upstream[0]), depth + 1)


def _family_findings(found: _Findings, comfy: Comfy) -> None:
    files: list[tuple[str, str]] = []
    bases: dict[str, tuple[str, str]] = {}
    addons: dict[str, tuple[str, str, str]] = {}
    for ref, node in found.api.items():
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for name, folder in _BASE_INPUTS.items():
            if isinstance(inputs.get(name), str):
                bases[ref] = (folder, inputs[name])
        for name, folder in _ADDON_INPUTS.items():
            if isinstance(inputs.get(name), str):
                addons[ref] = (folder, inputs[name], name)
    if not bases or not addons:
        return
    files = [*bases.values(), *((folder, value) for folder, value, _ in addons.values())]
    try:
        families = library.known_families(comfy, list(dict.fromkeys(files)))
    except ComfyError:
        return
    base_families = {ref: families.get(entry, ("", ""))[0] for ref, entry in bases.items()}
    only = {family for family in base_families.values() if family}
    for ref, (folder, value, name) in addons.items():
        family = families.get((folder, value), ("", ""))[0]
        if not family:
            continue
        base_ref = _base_of(found, ref) if name == "lora_name" else None
        base_family = base_families.get(base_ref or "", "") or (next(iter(only)) if len(only) == 1 else "")
        if not base_family or _FAMILY_ROOT.get(family, family) == _FAMILY_ROOT.get(base_family, base_family):
            continue
        what = "LoRA" if name == "lora_name" else "ControlNet"
        found.add(ref, "family_mismatch", "warning",
                  found.say(f"{what}「{value}」是 {family} 的,加载的大模型是 {base_family} 的",
                            f"The {what} “{value}” is for {family}, but the loaded base model is {base_family}"),
                  found.say(f"换一个 {base_family} 的 {what},或者换成 {family} 的大模型",
                            f"Use a {base_family} {what}, or switch to a {family} base model"), input_name=name)


def _refs_of_type(found: _Findings, class_type: str) -> list[str]:
    return [ref for ref, node in found.api.items() if str(node.get("class_type") or "") == class_type]


def _error_fix(found: _Findings, text: str) -> str:
    lowered = text.lower()
    if "out of memory" in lowered or "oom" in lowered.split():
        return found.say("显存不够:调小宽高或批次、换小一点的模型(fp8 / GGUF),或者先释放显存再跑",
                         "Out of memory: lower the size or batch, use a smaller model (fp8 / GGUF), or free VRAM first")
    if "value not in list" in lowered:
        return found.say("这一格的值这台机器上没有:在下拉里换成已有的,缺的模型先下载",
                         "That value isn't available on this machine: pick an existing one, or download the missing model")
    if "required input is missing" in lowered:
        return found.say("必填的输入没连:给它接上", "A required input is not connected: connect it")
    return found.say("按报错原文改这个节点;改完再跑一次", "Fix this node according to the error, then run again")


def _error_findings(found: _Findings, error: str, downloads: dict[str, dict[str, str]]) -> None:
    text = error.strip()[:MAX_ERROR]
    if not text:
        return
    hit = False
    for piece in re.split(r";\s*|\n", text):
        for mention in _NODE_MENTION.finditer(piece):
            ref = mention.group(1)
            if ref not in found.api and canvas.locate_ref(found.content, ref)[1] is None:
                continue
            hit = True
            said = piece.strip()[:600]
            found.add(ref, "last_run_error", "error", said, _error_fix(found, said))
    for folder, name in _MISSING_FILE.findall(text):
        for ref, node in found.api.items():
            inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
            if any(isinstance(value, str) and _norm(value) == _norm(name) for value in inputs.values()):
                hit = True
                base = _norm(name).split("/")[-1]
                url = (downloads.get(base) or {}).get("url", "")
                found.add(ref, "last_run_error", "error",
                          found.say(f"上次运行时 ComfyUI 找不到模型文件「{name}」({folder})", f"Last run: ComfyUI couldn't find the model file “{name}” ({folder})"),
                          found.say(f"把它放进 models/{folder}" + (f"(下载地址 {url})" if url else "") + ",或者换成已有的文件",
                                    f"Put it into models/{folder}" + (f" (download: {url})" if url else "") + ", or pick an existing file"))
    failed = _EXECUTION_FAILED.search(text)
    if failed:
        node_type, said = failed.group(1).strip(), failed.group(2).strip()[:600]
        refs = _refs_of_type(found, node_type)
        if refs:
            hit = True
            found.add(refs[0], "last_run_error", "error",
                      found.say(f"上次运行在 {node_type} 这里失败:{said}", f"Last run failed at {node_type}: {said}"),
                      _error_fix(found, said), class_type=node_type, refs=refs)
    if not hit:
        found.add("", "last_run_error", "error", text[:600], _error_fix(found, text))


def check(content: dict[str, Any], object_info: dict[str, Any], comfy: Comfy, locale: str, error: str = "") -> dict[str, Any]:
    """问题单(见模块说明)。`object_info` 是图里那几类节点的定义。"""
    notes: list[str] = []
    try:
        api = convert.to_api(content, object_info, locale)
    except ComfyError as exc:
        api = {}
        notes.append(str(exc))
    found = _Findings(content, api, object_info, locale)
    downloads = _declared_downloads(content)
    _missing_types(found, object_info, comfy)
    for ref, node in api.items():
        spec = object_info.get(str(node.get("class_type") or ""))
        if isinstance(spec, dict):
            _value_findings(found, ref, node, spec, downloads)
    _family_findings(found, comfy)
    _error_findings(found, error, downloads)
    findings = sorted(found.items, key=lambda one: (SEVERITY_ORDER.get(one["severity"], 9), one["ref"] == "", one["ref"]))
    counts = {level: sum(1 for one in findings if one["severity"] == level) for level in ("error", "warning")}
    return {"findings": findings, "counts": counts, "checked_nodes": len(api), "notes": notes}


def check_graph(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """`{"op": "check_graph", "content", "error"?}`。只问图里那几类节点的定义。"""
    content = live_graph(payload, locale)
    error = payload.get("error")
    if error is not None and not isinstance(error, str):
        raise ComfyError(say(locale, "上一次运行的报错得是一段文字", "The last-run error must be text."))
    object_info = node_catalog.classes(comfy, canvas.class_types(content))
    return check(content, object_info, comfy, locale, error or "")


__all__ = ["check", "check_graph"]
