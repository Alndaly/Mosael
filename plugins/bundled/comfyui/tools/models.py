"""这台 ComfyUI 上有哪些「模型」—— 以及一个模型 id 背后是哪张图。

两种来源,id 各不相撞:

- `builtin:txt2img` —— 内置的最小文生图(服务器上至少有一个 checkpoint 时才有)。装好 ComfyUI、
  下好一个模型,什么工作流都没存也能用;
- 其余 —— 用户在 ComfyUI 里**保存的每一个工作流**,id 就是它在 workflows/ 下的路径(以 `.json` 结尾)。

**表单是工作流的入口**(ADR 0045):一张保存的工作流有一个**完整工作流**入口(id 就是路径,全部能填的项)和它上面每张表单
各一个**表单**入口(id 是 `<路径>#<表单 id>`,如 `krea2-text-2-image.json#app`)。目录里每个入口一项;名字分两层,主名是
入口自己的(表单标题 / 文件名),「来自哪张工作流」放在 `group` 里,不拼成一句。

(此前还有一种:连接配置里粘贴的「API 模板」`api-workflow`,给转换认不出的工作流留条退路。1.17.0 删了 —— 导出的
API 格式 JSON 直接导进工作流库就会转成界面格式(workflow_import),它就是一张普通的保存的工作流。)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, NamedTuple

import app_form
import convert
import graph
from comfy_http import Comfy, is_workflow_path
from lines import ComfyError, say

BUILTIN = "builtin:txt2img"
#: 内置文生图叫什么。
BUILTIN_LABEL = {"zh": "内置文生图", "en": "Built-in text-to-image"}

#: 最小文生图,API 格式。checkpoint 用服务器上的第一个 —— 写死一个文件名的话,除了作者那台,
#: 每一台都跑不起来。
BUILTIN_GRAPH: dict[str, Any] = {
    "3": {"class_type": "KSampler", "inputs": {
        "cfg": 7, "denoise": 1, "sampler_name": "euler", "scheduler": "normal",
        "seed": "{{seed}}", "steps": "{{steps}}",
        "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{{checkpoint}}"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"batch_size": 1, "width": "{{width}}", "height": "{{height}}"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": "{{prompt}}"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": "{{negative}}"}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mosael", "images": ["8", 0]}},
}
#: 占位符没给值时用什么(用户没动那一格)。只对内置文生图有意义 —— 保存的工作流有它自己的值。
PLACEHOLDER_DEFAULTS = {"negative": "", "steps": 20, "width": 1024, "height": 1024}


def checkpoints(object_info: dict[str, Any]) -> list[str]:
    try:
        found = object_info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except (KeyError, IndexError, TypeError):
        return []
    return [str(one) for one in found] if isinstance(found, list) else []


class Loaded(NamedTuple):
    """一个模型 id 背后的那张图。"""

    api: dict[str, Any]
    #: 占位符的默认值(内置文生图;保存的工作流有它自己的值)
    defaults: dict[str, Any]
    #: 节点 id → 界面上的名字
    titles: dict[str, str]
    #: 工作流里 Mosael 的标记(应用表单、标成结果的节点,见 app_form);内置文生图没有
    marks: app_form.Marks = app_form.NONE
    #: ComfyUI 保存时写进图里的 id(见 Workflow.ident);内置文生图没有
    ident: str = ""


def load(comfy: Comfy, model_id: str, object_info: dict[str, Any], locale: str) -> Loaded:
    """一张图(工作流的路径,或内置文生图)→ API 图、占位符的默认值、节点名字、表单的标记。表单入口的 id 先经 `pick` 拆开。

    图只留 ComfyUI 真会跑的那部分(graph.live):目录说的、填进去的、提交的是同一张图 —— 悬空的画布节点不再冒充
    「尺寸」「张数」,下游被旁路的读图节点不再冒充一格输入。"""
    if model_id == BUILTIN:
        found = checkpoints(object_info)
        if not found:
            raise ComfyError(say(locale, "ComfyUI 里没有任何 checkpoint 模型 —— 先在 ComfyUI 里装一个",
                                 "ComfyUI has no checkpoint models. Install one in ComfyUI first."))
        return Loaded(graph.substitute_placeholders(BUILTIN_GRAPH, {"checkpoint": found[0]}), dict(PLACEHOLDER_DEFAULTS), {})
    try:
        ui_graph = comfy.fetch_workflow(model_id)
    except ComfyError as exc:
        if exc.status == 404:
            raise ComfyError(say(locale, f"ComfyUI 里已经没有工作流「{model_id}」了 —— 到插件页点「刷新模型」,或用 list_workflows 看看现在有哪些",
                                 f"ComfyUI no longer has the workflow “{model_id}”. Click Refresh models on the Plugins page, or call list_workflows to see what exists.")) from exc
        raise
    api = graph.live(convert.to_api(ui_graph, object_info, locale), object_info)
    return Loaded(api, {}, convert.titles_of(api), app_form.read(ui_graph), _ident(ui_graph))


def label_of(path: str) -> str:
    return path[:-5] if path.endswith(".json") else path


class Workflow(NamedTuple):
    """这台服务器上的一张图(保存的工作流,或内置文生图)。它有几个入口,见 `entries`。"""

    id: str
    label: Any
    api: dict[str, Any]
    titles: dict[str, str]
    #: 转不过来的原因;空串 = 没问题
    problem: str
    #: ComfyUI 保存工作流时写进图里的 id(新版前端的 UUID)。**改名、挪目录都不变**,工具名靠它稳住;
    #: 老版本存的图没有,是空串。
    ident: str = ""
    #: 工作流里 Mosael 的标记(应用表单、标成结果的节点,见 app_form)
    marks: app_form.Marks = app_form.NONE


#: 没起标题的表单叫什么(主名;副名里写着来自哪张工作流)。编辑器要求每张表单起标题(ADR 0045 §7),只有从上一版改写过来、
#: 当初没起标题的那张会是空的。
FORM_NAME = {"zh": "未命名表单", "en": "Untitled form"}


class Entry(NamedTuple):
    """一张图的一个入口(ADR 0045):完整工作流,或它上面的一张表单。目录里的一个模型、一个工具说的都是一个入口。"""

    #: 模型 id:完整入口是那张图的 id(路径 / `builtin:txt2img`),表单入口是 `<路径>#<表单 id>`
    id: str
    workflow: Workflow
    #: 空串 = 完整工作流
    form_id: str
    form: graph.Form
    #: 主名:表单入口是表单标题(没起就是 FORM_NAME),完整入口是这张图自己的名字(文件名去掉 `.json`)
    name: Any
    #: 这张图上有没有表单(完整入口用得上:有表单时它不进智能体的工具表,见 tooling.tool_for)
    formed: bool = False
    #: 在这张图的入口里排第几:完整工作流是 0,表单按文件里的顺序从 1 起(宿主据此排,见 group_of)
    order: int = 0


def entry_id(path: str, form_id: str) -> str:
    return f"{path}#{form_id}" if form_id else path


def split_id(model_id: str) -> tuple[str, str]:
    """模型 id → (那张图的 id, 表单 id)。以 `.json` 结尾的是完整入口(路径里本身带 `#` 的也是);否则在最后一个 `#` 切开,
    前一半以 `.json` 结尾、后一半是合法的表单 id 才是表单入口。别的原样交回(不是这台 ComfyUI 的模型,读的时候说找不到)。"""
    if model_id == BUILTIN or model_id.endswith(".json"):
        return model_id, ""
    path, sep, form_id = model_id.rpartition("#")
    if sep and path.endswith(".json") and app_form.FORM_ID_PATTERN.match(form_id):
        return path, form_id
    return model_id, ""


def entries(workflow: Workflow, object_info: dict[str, Any]) -> list[Entry]:
    """这张图的入口:完整工作流在前,表单按文件里的顺序。转不过来的图没有入口。"""
    if workflow.problem:
        return []
    resolved = app_form.resolve(workflow.marks, workflow.api, object_info, workflow.titles)
    formed = bool(resolved.forms)
    found = [Entry(workflow.id, workflow, "", resolved.full, workflow.label, formed)]
    for order, (form_id, form) in enumerate(resolved.forms.items(), start=1):
        found.append(Entry(entry_id(workflow.id, form_id), workflow, form_id, form, form.title or FORM_NAME, formed, order))
    return found


def group_of(entry: Entry) -> dict[str, Any] | None:
    """这个入口是哪张工作流的哪个入口(宿主据此把同一张的几个入口排在一起、副名写「来自 …」,见 docs/PLUGIN_MANIFEST)。
    内置文生图不是存着的工作流,没有。"""
    if entry.workflow.id == BUILTIN:
        return None
    return {"id": entry.workflow.id, "label": entry.workflow.label, "entry": "form" if entry.form_id else "full",
            "order": entry.order}


#: 一次性的改名(ADR 0045 §6):1.20 之前,一张有表单的图,它的路径 / 工具名指的是那张表单;从 1.20 起它们指完整工作流,
#: 表单搬到表单入口。宿主每个连接只做一次(按 `key` 记账),把存着的老引用改到表单入口 —— 跑起来和以前一样。
#: 只报 id 是 `app` 的那张(上一版那唯一一张改写过来的):从 1.20 之前直接升到这一版的人,文件改写成新格式之后照样做一次
#: (ADR 0045 §7);新建的表单从来没有老引用,不报。
MOVED_KEY = "form-entries"


def moved(found: list[Entry], name_of: Any = None) -> list[dict[str, str]]:
    """`found` 里每张图 id 为 `app` 的那个表单入口一条 `{key, from, to}`:`from` 是这张图完整入口的名字,`to` 是表单入口的。
    `name_of` 把入口换成要报的名字(工具名);不给就是模型 id。"""
    name_of = name_of or (lambda entry: entry.id)
    by_workflow = {one.workflow.id: one for one in found if not one.form_id}
    out: list[dict[str, str]] = []
    for one in found:
        full = by_workflow.get(one.workflow.id)
        if one.form_id != app_form.FORM_ID or full is None:
            continue
        source, target = name_of(full), name_of(one)
        if source and target and source != target:
            out.append({"key": MOVED_KEY, "from": source, "to": target})
    return out


def pick(comfy: Comfy, model_id: str, object_info: dict[str, Any], locale: str) -> tuple[Loaded, Entry]:
    """模型 id → 那张图和它的那个入口。图不在了照 `load` 说;图还在、表单没了另说一句。"""
    path, form_id = split_id(model_id)
    loaded = load(comfy, path, object_info, locale)
    label = BUILTIN_LABEL if path == BUILTIN else label_of(path)
    workflow = Workflow(path, label, loaded.api, loaded.titles, "", loaded.ident, loaded.marks)
    for one in entries(workflow, object_info):
        if one.id == entry_id(path, form_id):
            return loaded, one
    if loaded.marks.upgradable:
        raise outdated(path, locale)
    raise ComfyError(say(locale, f"工作流「{label_of(path)}」上已经没有这张表单了 —— 在工作流库或工作台里看看它现在有哪些表单",
                         f"The workflow “{label_of(path)}” no longer has this form. Check its forms in the workflow library "
                         "or the workbench."))


def outdated(path: str, locale: str) -> ComfyError:
    """表单还是上一版的格式(这一版不读):说清楚去哪升级,别说成「表单没了」。"""
    return ComfyError(say(locale, f"工作流「{label_of(path)}」的表单还是旧格式,这一版插件读不到 —— 到这个连接的工作流库里点"
                                  "「查看并升级」,升级之后就能用了",
                          f"The forms on the workflow “{label_of(path)}” are in the old format, which this version of the "
                          "plugin doesn't read. Open this connection's workflow library and click “Review and upgrade”; "
                          "the forms work again once upgraded."))


def _ident(ui_graph: Any) -> str:
    raw = ui_graph.get("id") if isinstance(ui_graph, dict) else None
    return raw.strip() if isinstance(raw, str) and len(raw.strip()) >= 8 else ""


def each(comfy: Comfy, object_info: dict[str, Any], locale: str) -> Iterator[Workflow]:
    """这台服务器上的每张图(它们的入口见 `entries`)。

    一张图拉不下来 / 转不过来,照样交出来(带着原因)—— 目录里跳过它,`list_workflows` 把原因说出来:
    智能体问「有哪些工作流」时,一张静默消失的图比一张标着「转换失败」的图更让人摸不着头脑。工作流目录里
    不是 .json 的文件(拷进去的压缩包)也一样带着原因交出来。
    """
    if checkpoints(object_info):
        loaded = load(comfy, BUILTIN, object_info, locale)
        yield Workflow(BUILTIN, BUILTIN_LABEL, loaded.api, loaded.titles, "")
    workflows, others = comfy.saved_files()
    for path in workflows:
        try:
            ui_graph = comfy.fetch_workflow(path)
            api = graph.live(convert.to_api(ui_graph, object_info, locale), object_info)
        except Exception as exc:  # noqa: BLE001 — 一张图拉不下来 / 转不过来,别的照常列
            yield Workflow(path, label_of(path), {}, {}, str(exc) or type(exc).__name__)
            continue
        if not api:
            yield Workflow(path, label_of(path), {}, {}, say(locale, "工作流是空的", "The workflow is empty"), _ident(ui_graph))
            continue
        yield Workflow(path, label_of(path), api, convert.titles_of(api), "", _ident(ui_graph), app_form.read(ui_graph))
    for path in others:
        yield Workflow(path, path, {}, {}, _not_a_workflow(path, locale))


def _not_a_workflow(path: str, locale: str) -> str:
    """工作流目录里一个不是 .json 的文件为什么用不了。"""
    if path.lower().endswith(".zip"):
        return say(locale,
                   "这是一个压缩包,不是工作流:ComfyUI 自己也打不开它。解压后在 ComfyUI 里打开里面的 .json(压缩包里带着"
                   "自定义节点的话先装好),另存一份,Mosael 就认得出了",
                   "This is a zip archive, not a workflow, and ComfyUI can't open it either. Unzip it, open the .json inside "
                   "in ComfyUI (install any custom nodes it ships with first) and save it again; Mosael will then pick it up.")
    return say(locale, "这不是 ComfyUI 保存的工作流(.json),Mosael 不读它",
               "This is not a workflow saved by ComfyUI (.json), so Mosael doesn't read it.")


def catalog(comfy: Comfy, locale: str) -> dict[str, Any]:
    """这台服务器现在有哪些模型:每张图的每个入口一项(`models`),加上一次性的改名(`moved`,见 MOVED_KEY)。一张图转不过来
    就跳过它,不让它拖垮整份清单。

    **不交出文件的图不是模型**(反推提示词、打标签这类只交出一段字的,见 graph.media_outputs):生成是
    「一段提示词 → 一份成片」,它们交不出成片。它们照样是工具(每个入口一个,见 tooling),在工作流里、画板上用。

    `library_upgrades`:这台服务器上有几张工作流的表单还是上一版的格式(app_form.upgradable,交不交出文件都算)—— 宿主据此
    发一次通知,工作流库里「查看并升级」(见 workflow_library.upgrade_marks、docs/PLUGIN_MANIFEST)。那几张上一版的表单入口
    (`<路径>#app`)现在为什么不在,宿主问 `explain`。
    """
    object_info = comfy.object_info()
    models: list[dict[str, Any]] = []
    listed: list[Entry] = []
    upgrades = 0
    for workflow in each(comfy, object_info, locale):
        upgrades += workflow.marks.upgradable
        if workflow.problem or not graph.media_outputs(workflow.api, object_info, workflow.titles):
            continue
        for entry in entries(workflow, object_info):
            model = graph.describe(entry.id, entry.name, workflow.api, object_info, workflow.titles, entry.form)
            if entry.id == BUILTIN:
                model["parameters"]["size"]["default"] = "1024x1024"
                model["prompt_dialect"] = "sd-tags"
            group = group_of(entry)
            if group is not None:
                model["group"] = group
            models.append(model)
            listed.append(entry)
    return {"models": models, "moved": moved(listed), "library_upgrades": upgrades}


#: 一次最多解释几个模型 id(宿主问的是界面上正指着的那几个,一般一两个)。
MAX_EXPLAIN = 50


def _form_of(label: str) -> dict[str, str]:
    """一张读不到标题的表单叫什么(上一版格式的、已经删掉的):「X 的表单」。"""
    return {"zh": f"{label} 的表单", "en": f"Form of {label}"}


def explain(comfy: Comfy, ids: Any, locale: str) -> dict[str, Any]:
    """宿主记着、目录里没有的几个模型 id 现在为什么不在(ADR 0045):每个一条 `{id, label, group, reason, upgrade}`。`label`
    是这个入口的主名(表单这时多半读不到标题了,写「X 的表单」),`group` 和目录里的一样(来自哪张工作流),`reason` 是给人看的
    一句(按语言分),`upgrade` 为真表示修法是到工作流库里「查看并升级」。不是这台 ComfyUI 的 id(内置文生图、认不出的)不回。

    分开说的几种:那张工作流的表单还是上一版的格式(要升级);工作流还在、这张表单没了(删掉了);工作流不在了(改了名、
    挪了文件夹或删掉了);工作流在、入口也在文件里,只是转不过来或交不出成片(照读它时的原因说)。只读,不写那台机器。"""
    if not isinstance(ids, list) or any(not isinstance(one, str) for one in ids):
        raise ComfyError(say(locale, "要解释的模型 id 形状不对", "The model ids to explain are malformed."))
    saved = set(comfy.saved_files()[0])
    object_info: dict[str, Any] | None = None
    out: list[dict[str, Any]] = []
    for model_id in dict.fromkeys(ids[:MAX_EXPLAIN]):
        path, form_id = split_id(model_id)
        if not is_workflow_path(path):
            continue
        label = label_of(path)
        found = {"id": model_id, "label": _form_of(label) if form_id else label,
                 "group": {"id": path, "label": label, "entry": "form" if form_id else "full"}, "upgrade": False}
        try:
            ui_graph = comfy.fetch_workflow(path) if path in saved else None
        except ComfyError as exc:
            if exc.status != 404:
                raise
            ui_graph = None
        marks = app_form.read(ui_graph) if ui_graph is not None else app_form.NONE
        if ui_graph is None:
            found["reason"] = {
                "zh": f"这台 ComfyUI 上已经没有工作流「{label}」了 —— 可能改了名、挪了文件夹或删掉了。到工作流库里找到它,"
                      "再在这里重新选一次",
                "en": f"This ComfyUI no longer has the workflow “{label}”: it may have been renamed, moved to another folder "
                      "or deleted. Find it in the workflow library and choose it here again."}
        elif form_id and marks.upgradable:
            found["reason"], found["upgrade"] = outdated(path, locale).said, True
        elif form_id and form_id not in {one.id for one in marks.forms}:
            found["reason"] = {
                "zh": f"工作流「{label}」上已经没有这张表单了(删掉了)—— 换成它别的表单或完整工作流",
                "en": f"The workflow “{label}” no longer has this form (it was deleted). Choose another of its forms or the "
                      "full workflow."}
        else:
            object_info = object_info if object_info is not None else comfy.object_info()
            problem: dict[str, str] | str = ""
            try:
                api = graph.live(convert.to_api(ui_graph, object_info, locale), object_info)
                if not api or not graph.media_outputs(api, object_info, convert.titles_of(api)):
                    problem = {"zh": f"工作流「{label}」交不出图片、视频或声音,不能拿来生成",
                               "en": f"The workflow “{label}” produces no image, video or audio, so it can't be used for "
                                     "generation."}
            except ComfyError as exc:
                problem = exc.said
            except Exception as exc:  # noqa: BLE001 — 转不过来就照它的原因说
                problem = str(exc) or type(exc).__name__
            if not problem:
                continue
            found["reason"] = problem
        out.append(found)
    return {"models": out}


#: 判「模型清单有没有变」时顺带看的模型目录:换了一个 checkpoint / LoRA,参数里的下拉就该跟着变。
_WATCHED_FOLDERS = ("checkpoints", "loras", "diffusion_models", "unet", "vae", "upscale_models", "controlnet")


def plugin_version() -> str:
    """这个插件自己的版本(清单里的 `version`)。指纹带上它:插件升级后怎么描述一张图可能变了。"""
    try:
        manifest = json.loads((Path(__file__).resolve().parent.parent / "mosael.plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(manifest.get("version") or "")


def fingerprint(comfy: Comfy) -> str:
    """模型清单的**指纹**:插件自己的版本、保存的工作流(路径 + 大小 + 修改时间)、几个模型目录的文件名。

    带上插件版本:同一批工作流,插件升级后描述出来的东西可能变了(默认张数、尺寸、哪些算产出),宿主库里缓存的
    模型和工具清单得跟着重拉,而不是等用户改了工作流或手动点「刷新模型」。

    宿主隔一会儿问一次(见 docs/PLUGIN_MANIFEST 的「目录变了就刷新」):指纹没变就不必把每张工作流
    重新拉一遍、转一遍。这里只列目录,不取任何一张图的内容 —— 一百张工作流也就一个请求。
    """
    digest = hashlib.sha256()
    digest.update(f"plugin {plugin_version()}\n".encode("utf-8"))
    listed = [item for item in comfy.workflow_listing() if is_workflow_path(str(item.get("path") or ""))]
    for item in sorted(listed, key=lambda one: str(one.get("path"))):
        digest.update(f"{item.get('path')}|{item.get('size')}|{item.get('modified')}\n".encode("utf-8"))
    folders = comfy.model_folders()
    for folder in sorted(set(folders or ()) & set(_WATCHED_FOLDERS)):
        digest.update(f"[{folder}]".encode("utf-8"))
        for name in sorted(comfy.models_in(folder)):
            digest.update(name.encode("utf-8") + b"\n")
    return digest.hexdigest()[:32]
