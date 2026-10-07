"""插件替宿主做**生成**:插件这一侧的契约(见 docs/adr/0020 与 PLUGIN_MANIFEST 的「替宿主做生成」)。

认领了 `generation` 能力的那个工具收两种 `op`:

    {"op": "models"}                      → {"models": [...]}      一问一答,问这个实例有哪些模型
    {"op": "generate", "model": …, …}     → 流式:进度、回执,最后给产出

这里只做**插件那一侧**的事:把插件说的话收成规整的形状(模型清单里什么该认、什么该丢),把输入
文件拷进去、把产出拿出来。**不认识生成领域** —— 模型怎么变成连接和模型行、参数面怎么翻成内核的
描述符,是 domain/generation/plugin_connections 的事(方向和 media_bridge 一样:插件域不 import 生成域)。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance
from app.domain.plugins import artifacts
from app.domain.plugins import egress as plugin_egress
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import GENERATION
from app.domain.plugins.runtime import StreamHooks

#: 问一次模型清单最多等多久。一台 ComfyUI 上百张工作流,每张拉一次图 —— 本机/局域网上几秒的事。
CATALOG_TIMEOUT_SECONDS = 60.0
#: 一个实例最多列多少个模型。再多选择器就没法用了,而且多半是插件在列一个不该列的东西。
MAX_MODELS = 500
#: 插件可以说的模型种类。宿主今天只把 image / video 接进选择器,别的照收不误(列出来,不进选择器)。
MODEL_KINDS = ("image", "video", "audio")

_MODEL_ID = re.compile(r"^[^\x00-\x1f]{1,160}$")
#: 参数键:工作流里的「节点.输入」、宿主词汇里的 `seed`、`duration_seconds`……不收空格和控制字符。
_PARAMETER_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:\-]{0,79}$")
#: `x-model-folder`:这一格选的是哪个模型目录的文件(ComfyUI 的 checkpoints / loras……)。只收一段像目录名的字:
#: 表单拿它去模型库对文件,不是路径。
_MODEL_FOLDER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
_PARAMETER_TYPES = ("integer", "number", "string", "boolean")
#: 一个参数最多列多少个可选值(ComfyUI 的 checkpoint 下拉动辄几十个,上千就不是下拉了)。
_MAX_ENUM = 1000
#: 一个模型最多几个输入槽位、每个槽位最多几份。
_MAX_INPUTS = 16
_MAX_INPUT_COUNT = 32
#: 一次运行最多说交回几份(一张工作流几十个保存节点就不是一个「模型」了,多半是插件数错了)。
_MAX_OUTPUTS_PER_RUN = 64


@dataclass(frozen=True)
class PluginModel:
    """插件说的一个模型,收成规整的形状。给人看的字已经按当前语言挑好。"""

    id: str
    label: str
    kind: str
    modes: tuple[str, ...] = ()
    #: 键 → JSON Schema 片段(`type` / `enum` / `default` / `minimum` / `maximum` / `multipleOf` /
    #: `title` / `description` / `x-advanced` / `x-multiline`),只留这些。
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: `{role, max, required, labels}`:`labels` 是这个角色的槽位按顺序叫什么(ComfyUI 一张工作流十个读图节点,
    #: 「人物」「背景」……,ADR 0038 §4),没给是空的。角色认不认,由宿主侧判(它才知道有哪些角色)。
    inputs: tuple[dict[str, Any], ...] = ()
    max_outputs: int = 1
    #: 一次运行交回几份(张数为 1、参数都按缺省时):ComfyUI 的一张工作流有几个保存节点就是几。宿主据此一次摆好
    #: 那么多格占位(见 generation.catalog.outputs_per_run)。
    outputs_per_run: int = 1
    prompt_dialect: str = ""
    #: 提示词要不要写:`required` / `optional` / `none`(空串 = 没说,按 required)。认不认这个值由宿主侧判
    #: (生成域的 PROMPT_MODES)—— 和 `inputs` 的角色同一条:插件域只收形状,不认识生成的词汇。
    prompt: str = ""
    #: 提示词可以不写时,**不写就用的那一句**(ComfyUI:工作流里存着的那句)。没给是空串。
    prompt_default: str = ""
    #: 作者给这个模型挑的那张表(ComfyUI 的精简表单,ADR 0038 §2):`{title, description, items: [{key, label}]}`,
    #: `items` 按表上的顺序。没有就是 None —— 按参数各自的样子摆。名字按语言分的原样留着,给人看时再挑。
    form: dict[str, Any] | None = None


@dataclass(frozen=True)
class Catalog:
    """一次 `op: models` 的结果。`fingerprint` 是插件给的「这份清单的指纹」(可以没有,见 `fingerprint`)。"""

    models: list[PluginModel]
    fingerprint: str = ""


#: 指纹最长多少。它只拿来比「变没变」,不是存档。
_MAX_FINGERPRINT = 200


def catalog(db: Session, instance: PluginInstance) -> Catalog:
    """问这个实例现在有哪些模型。认不出的条目**丢掉**,不让一条坏条目拖垮整份清单。"""
    output = tools.invoke_host(db, instance.id, GENERATION, {"op": "models"}, timeout=CATALOG_TIMEOUT_SECONDS)
    raw = output.get("models")
    if not isinstance(raw, list):
        raise PluginDomainError("pluginErr_generationBadModels", name=instance.name, shape='{"models": [...]}')
    manifest = inst.manifest_for(db, instance)
    models: list[PluginModel] = []
    seen: set[str] = set()
    for entry in raw[:MAX_MODELS]:
        model = _model(entry, manifest.text)
        if model is not None and model.id not in seen:
            seen.add(model.id)
            models.append(model)
    return Catalog(models=models, fingerprint=_fingerprint(output))


def _fingerprint(output: dict[str, Any]) -> str:
    raw = output.get("fingerprint")
    return raw.strip()[:_MAX_FINGERPRINT] if isinstance(raw, str) else ""


def _model(entry: Any, text: Any) -> PluginModel | None:
    if not isinstance(entry, dict):
        return None
    model_id = str(entry.get("id") or "").strip()
    kind = str(entry.get("kind") or "").strip().lower()
    if not _MODEL_ID.match(model_id) or kind not in MODEL_KINDS:
        return None
    modes = tuple(str(one) for one in (entry.get("modes") or []) if isinstance(one, str) and one.strip())
    raw_outputs = entry.get("max_outputs")
    max_outputs = int(raw_outputs) if isinstance(raw_outputs, int) and not isinstance(raw_outputs, bool) else 1
    per_run = entry.get("outputs_per_run")
    outputs_per_run = int(per_run) if isinstance(per_run, int) and not isinstance(per_run, bool) else 1
    return PluginModel(
        id=model_id,
        label=text(entry.get("label")).strip() or model_id,
        kind=kind,
        modes=modes,
        parameters=parameters(entry.get("parameters"), text),
        inputs=_inputs(entry.get("inputs"), text),
        max_outputs=min(max(max_outputs, 1), 16),
        outputs_per_run=min(max(outputs_per_run, 1), _MAX_OUTPUTS_PER_RUN),
        prompt_dialect=str(entry.get("prompt_dialect") or "").strip()[:40],
        prompt=str(entry.get("prompt") or "").strip().lower()[:16] if isinstance(entry.get("prompt"), str) else "",
        prompt_default=entry["prompt_default"].strip()[:_MAX_PROMPT_DEFAULT] if isinstance(entry.get("prompt_default"), str) else "",
        form=_form(entry.get("form"), text),
    )


#: 「不写就用的那句提示词」最长收多少字;表单最多几项、标题和说明最长多少字(和插件那边 app_form 的上限一样)。
_MAX_PROMPT_DEFAULT = 4000
_MAX_FORM_ITEMS = 200
_MAX_FORM_TITLE = 120
_MAX_FORM_DESCRIPTION = 1000
#: 表单一项的键:宿主的提示词框(`prompt`),或者参数键 / 素材角色(和参数键同一种写法)。
_FORM_KEY = re.compile(r"^(prompt|[A-Za-z0-9_][A-Za-z0-9_.:\-]{0,79})$")


def _form(raw: Any, text: Any) -> dict[str, Any] | None:
    """插件说的那张表收成规整的形状:认不出的项丢掉,同一个键只留第一次。一项都没有、也没有标题的不算一张表。"""
    if not isinstance(raw, dict):
        return None
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw.get("items") or []:
        if not isinstance(entry, dict) or len(items) >= _MAX_FORM_ITEMS:
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not _FORM_KEY.match(key) or key in seen:
            continue
        seen.add(key)
        items.append({"key": key, "label": _localizable(entry.get("label"), text, 120)})
    title = _localizable(raw.get("title"), text, _MAX_FORM_TITLE)
    if not items and not title:
        return None
    return {"title": title, "description": _localizable(raw.get("description"), text, _MAX_FORM_DESCRIPTION), "items": items}


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) and not (isinstance(value, float) and value != value)


def parameters(raw: Any, text: Any) -> dict[str, dict[str, Any]]:
    """插件说的参数(键 → JSON Schema 片段)收成规整的形状:认不出的键、类型整项丢掉,只留认得的那几个字段。
    生成目录收它;工作流库的应用表单编辑器收的每一项的 `schema` 也过它 —— 预览和真的表单是同一套形状。"""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, spec in raw.items():
        if not isinstance(key, str) or not _PARAMETER_KEY.match(key) or not isinstance(spec, dict):
            continue
        kind = spec.get("type")
        if kind not in _PARAMETER_TYPES:
            continue
        clean: dict[str, Any] = {"type": kind}
        # 名字和说明**按语言分的就原样留着**,到给人看的那一刻再挑(见 generation/resolution):
        # 目录是在后台刷新的(启动时、隔一会儿),刷新那一刻的语言不是看的人的语言。
        title = _localizable(spec.get("title"), text, 120)
        if title:
            clean["title"] = title
        description = _localizable(spec.get("description"), text, 500)
        if description:
            clean["description"] = description
        enum = spec.get("enum")
        if isinstance(enum, list):
            values = [one for one in enum if _scalar(one)][:_MAX_ENUM]
            if values:
                clean["enum"] = values
        # 推荐值(不是限制):尺寸给的是几档推荐、手填的也收时用它,不用 enum(见 generation/plugin_connections.descriptor)。
        examples = spec.get("examples")
        if isinstance(examples, list) and "enum" not in clean:
            suggested = [one for one in examples if _scalar(one)][:_MAX_ENUM]
            if suggested:
                clean["examples"] = suggested
        if _scalar(spec.get("default")):
            clean["default"] = spec["default"]
        for bound in ("minimum", "maximum", "multipleOf"):
            value = spec.get(bound)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value:
                clean[bound] = value
        # 和工具入参同一套扩展键(见 plugins/nodes 的 x-advanced):留空也能跑的收进「高级」。
        if spec.get("x-advanced") is True or spec.get("advanced") is True:
            clean["x-advanced"] = True
        if spec.get("x-multiline") is True and kind == "string":
            clean["x-multiline"] = True
        # 「张数」数的是**跑几遍**(ComfyUI:每遍按工作流原样出它那批,见 docs/PLUGIN_MANIFEST「替宿主做生成」),
        # 和一遍里每个结果节点出几张(`x-batch`,判得出来才有)。
        if spec.get("x-count-unit") == "runs" and kind == "integer":
            clean["x-count-unit"] = "runs"
            batch = spec.get("x-batch")
            if isinstance(batch, int) and not isinstance(batch, bool) and batch >= 1:
                clean["x-batch"] = min(batch, _MAX_OUTPUTS_PER_RUN)
        # 选模型文件的那一格写明是哪个模型目录的(生成表单据此从这个连接的模型库取缩略图、底模、触发词)
        folder = spec.get("x-model-folder")
        if isinstance(folder, str) and _MODEL_FOLDER.match(folder) and "enum" in clean:
            clean["x-model-folder"] = folder
        # 可选值的名字(「结果取自」的选项是节点 id,给人看的是节点标题)和每个可选值一次交回几份:
        # 只认可选值里有的,对不上的丢掉。
        choices = {str(one) for one in clean.get("enum") or ()}
        labels = spec.get("x-enum-labels")
        if isinstance(labels, dict) and choices:
            named = {str(value): label for value, one in labels.items()
                     if str(value) in choices and (label := _localizable(one, text, 120))}
            if named:
                clean["x-enum-labels"] = named
        counts = spec.get("x-outputs-per-run")
        if isinstance(counts, dict) and choices:
            counted = {str(value): min(one, _MAX_OUTPUTS_PER_RUN) for value, one in counts.items()
                       if str(value) in choices and isinstance(one, int) and not isinstance(one, bool) and one >= 1}
            if counted:
                clean["x-outputs-per-run"] = counted
        out[key] = clean
    return out


def _localizable(value: Any, text: Any, limit: int) -> str | dict[str, str]:
    """一段给人看的字:普通字符串,或 `{"zh": …, "en": …}`(只留字符串值)。空的回空串。"""
    if isinstance(value, dict):
        kept = {str(lang)[:16]: one.strip()[:limit] for lang, one in value.items() if isinstance(one, str) and one.strip()}
        return kept or ""
    return text(value).strip()[:limit]


def _inputs(raw: Any, text: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, Any]] = []
    for entry in raw[:_MAX_INPUTS]:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "").strip()
        if not role:
            continue
        count = entry.get("max")
        limit = int(count) if isinstance(count, int) and not isinstance(count, bool) else 1
        most = min(max(limit, 1), _MAX_INPUT_COUNT)
        raw_labels = entry.get("labels")
        labels = [_localizable(one, text, 120) for one in raw_labels[:most]] if isinstance(raw_labels, list) else []
        out.append(
            {
                "role": role,
                "max": most,
                "required": entry.get("required") is True,
                # 空的那一格(插件没给名字)留空串占位:名字按槽位顺序对,不能往前挪
                "labels": labels if any(labels) else [],
            }
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# 一次生成
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerationCall:
    """宿主要插件做的那一次。`inputs` 是 (角色, 本地文件):**调用方负责它们是能交出去的文件**
    (生成执行器只交素材库里、本工作区的素材)—— 这里只负责拷一份再交。"""

    model: str
    kind: str
    prompt: str
    negative_prompt: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    inputs: tuple[tuple[str, Path], ...] = ()
    #: 重启后接着等的那个远端任务(插件上次用 `task` 事件交回的回执)。有它就**不再提交**。
    resume: dict[str, Any] | None = None
    #: 工作台画布上现在这张(ADR 0038 §6):插件跑它而不是模型存着的那张(`prompt` / `workflow` / `client_id`)。
    graph: dict[str, Any] | None = None


@dataclass(frozen=True)
class GenerationOutcome:
    paths: list[Path]
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    #: 每份产出实际用的参数(和 paths 一一对应),插件在产出项上写的 `parameters`(只收标量)。
    output_parameters: list[dict[str, Any]] = field(default_factory=list)
    #: 插件说的一句话(`note`):比如循环里有一次失败了,出来的照样交回、说清成功了几张。
    note: str = ""


#: 一份产出上的参数最多记几个、说明最长多少字。
_MAX_OUTPUT_PARAMETERS = 16
_MAX_NOTE = 500


def _output_parameters(raw: Any) -> dict[str, Any]:
    """产出项上的 `parameters`:只收标量值,键是普通的参数名。"""
    if not isinstance(raw, dict):
        return {}
    kept = {key: value for key, value in raw.items() if isinstance(key, str) and _PARAMETER_KEY.match(key) and _scalar(value)}
    return dict(list(kept.items())[:_MAX_OUTPUT_PARAMETERS])


#: 产出最多几份。一次生成交回几百个文件,多半是插件把中间帧也交回来了。
MAX_OUTPUTS = 64


def generate(
    db: Session,
    instance_id: str,
    call: GenerationCall,
    *,
    output_dir: Path,
    hooks: StreamHooks,
) -> GenerationOutcome:
    """做一次生成。产出**挪进** `output_dir`(暂存目录随后就删),返回它们的路径。"""
    instance = db.get(PluginInstance, instance_id)
    if instance is None:
        raise PluginDomainError("pluginErr_instanceNotFound")
    name = instance.name
    #: 产出若是一个地址,由后端替这个连接去下 —— 走这个连接的出站决定(和插件进程拿到的是同一个,见 egress)。
    egress = plugin_egress.resolve(db, instance, inst.manifest_for(db, instance))
    collected: list[Path] = []
    parameters: list[dict[str, Any]] = []
    extras: dict[str, Any] = {}
    # 调用记录里留的那一份:不带本地路径(那是一次性的暂存路径),只说挂了哪几种素材。
    recorded = {
        "op": "generate",
        "model": call.model,
        "kind": call.kind,
        "prompt": call.prompt,
        "negative_prompt": call.negative_prompt,
        "parameters": call.parameters,
        "inputs": [role for role, _ in call.inputs],
        "resume": call.resume is not None,
        #: 画布上的那张图不进调用记录(几百 KB),只记一句是它
        **({"graph": True} if call.graph is not None else {}),
    }

    def prepare(scratch: Path) -> dict[str, Any]:
        inbox = scratch / "inputs"
        inbox.mkdir(parents=True, exist_ok=True)
        inputs: list[dict[str, str]] = []
        for index, (role, source) in enumerate(call.inputs, start=1):
            # **拷一份再给**:插件是第三方代码,它改坏了、删掉了,伤到的只是副本。
            target = inbox / f"{index:02d}-{role}{source.suffix}"
            shutil.copy2(source, target)
            inputs.append({"role": role, "path": str(target)})
        return {
            "op": "generate",
            "model": call.model,
            "kind": call.kind,
            "prompt": call.prompt,
            "negative_prompt": call.negative_prompt,
            "parameters": call.parameters,
            "inputs": inputs,
            "resume": call.resume,
            **({"graph": call.graph} if call.graph is not None else {}),
        }

    def collect(output: dict[str, Any], scratch: Path) -> dict[str, Any]:
        specs = output.get("outputs")
        if not isinstance(specs, list) or not specs:
            raise PluginDomainError("pluginErr_generationNoOutput", name=name)
        output_dir.mkdir(parents=True, exist_ok=True)
        for index, spec in enumerate(specs[:MAX_OUTPUTS], start=1):
            if not isinstance(spec, dict):
                continue
            # 和工具产出同一套规矩(落点受限、单份上限、只认 http(s)),见 artifacts.fetch。
            got = artifacts.fetch(spec, scratch, egress=egress)
            target = output_dir / f"{index:02d}-{got.name}"
            shutil.move(str(got), target)
            collected.append(target)
            parameters.append(_output_parameters(spec.get("parameters")))
        if not collected:
            raise PluginDomainError("pluginErr_generationNoOutput", name=name)
        usage = output.get("usage")
        raw = output.get("raw")
        extras["usage"] = dict(usage) if isinstance(usage, dict) else {}
        extras["raw"] = dict(raw) if isinstance(raw, dict) else {}
        note = output.get("note")
        extras["note"] = note.strip()[:_MAX_NOTE] if isinstance(note, str) else ""
        recorded_output: dict[str, Any] = {"outputs": [path.name for path in collected], "usage": extras["usage"]}
        if any(parameters):
            recorded_output["parameters"] = parameters
        if extras["note"]:
            recorded_output["note"] = extras["note"]
        return recorded_output

    tools.invoke_host(db, instance_id, GENERATION, recorded, prepare=prepare, collect=collect, hooks=hooks)
    return GenerationOutcome(paths=collected, usage=extras.get("usage", {}), raw=extras.get("raw", {}),
                             output_parameters=parameters if any(parameters) else [], note=extras.get("note", ""))


__all__ = [
    "CATALOG_TIMEOUT_SECONDS",
    "Catalog",
    "GENERATION",
    "GenerationCall",
    "GenerationOutcome",
    "MODEL_KINDS",
    "PluginModel",
    "catalog",
    "generate",
]
