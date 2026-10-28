"""节点输入绑定:数据边取值 + config 插值。

引擎(engine.py)和循环体子图(executors/loops.py)对节点输入的处理必须完全一致,
这份一致性以前靠两处内联代码保持——现在收敛到这里,成为唯一实现。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows.graph_rules import (
    NESTED_BODY_RAW_KEYS,
    NESTED_BODY_TYPES,
    interpolate,
    VARIABLE_RE,
    interpolate_json_text,
)
from app.db.models import Asset
from app.domain.generation.operations import takes_source_role
from app.domain.generation_catalog.descriptors.shared import SOURCE_ROLE_LABELS, SOURCE_ROLE_MEDIA
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.id_values import id_list
from app.domain.workflows.node_types import NODE_TYPES, config_data_type, config_media, field_name, output_data_type

# 内嵌子图的节点(循环体、subgraph)的 body/output/condition 引用的是**子作用域 / 子图内部节点**
# ({{loop.*}}、{{input.*}}、{{body_node.x}}),绝不能在外层作用域解析——它们要留到执行器里对
# 子上下文插值(循环每迭代一次、subgraph 跑完一次)。NESTED_BODY_RAW_KEYS 就是为此保留原文的字段。
# condition 只有 loop_while 用;subgraph 没有,列表里多一个键只是「存在才 pop」,无副作用。
# 类型集合与保留键的单一真源在 app.domain.workflows(校验时的「不下钻」也复用同一份)。


def apply_data_edges(
    node_id: str,
    config: dict[str, Any],
    edges: list[dict[str, Any]],
    context: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """数据边(kind="data")把上游输出值绑到目标输入,优先于字面量 / 内联 {{var}}。
    上游已执行(数据边同时是排序约束)才有值;拿不到就跳过、保留原字面量。

    **在插值之后调用,绑上来的值不再参与插值。** 上游的值是数据,不是模板:此前先绑后插值,
    一段 LLM 回答、一段抓回来的网页里恰好写着 `{{start.api_key}}`,就会在下游被换成开始节点
    的那个值(或被吞成空串)。规范化把每一个精确引用都升级成了数据边,所以几乎所有绑定都走
    这里。组合模板「前缀{{llm.text}}」的插值本来就只替换一趟(re.sub 不回扫替换进去的文字),
    两种写法由此一致:上游的值在任何一条路上都不再被当成模板。
    """
    for edge in edges:
        if str(edge.get("kind", "")) != "data" or str(edge.get("target", "")) != node_id:
            continue
        source = str(edge.get("source", ""))
        output = str(edge.get("source_output", ""))
        target_input = str(edge.get("target_input", ""))
        value = _path_value(context.get(source), output)
        if target_input and value is not _MISSING:
            _set_existing_path(config, target_input, value)
    return config


_MISSING = object()


def _path_value(value: Any, path: str) -> Any:
    """数据端口允许指向结构化输出里的叶子，例如 ``output.note_id`` / ``items.0.id``。"""
    current = value
    for part in path.split("."):
        if not part:
            return _MISSING
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
            continue
        return _MISSING
    return current


def _set_existing_path(config: dict[str, Any], path: str, value: Any) -> None:
    """写已有的对象/数组叶子；路径不存在时按旧契约写顶层键，兼容已保存的普通输入。"""
    parts = [part for part in path.split(".") if part]
    current: Any = config
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            config[path] = value
            return
    if not parts:
        config[path] = value
        return
    leaf = parts[-1]
    if isinstance(current, dict) and leaf in current:
        current[leaf] = value
    elif isinstance(current, list) and leaf.isdigit() and int(leaf) < len(current):
        current[int(leaf)] = value
    else:
        config[path] = value


def check_number_fields(node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """声明成数字(`"type": "number"`)的字段,插值、绑定之后必须真是数字 —— 或者留空。

    **按声明查一遍,所有节点一条规矩。** 此前各执行体自己 `float(config.get(...))`:语速填了
    「快一点」、或者一个引用落成了一段文字,抛出来的是 `could not convert string to float` ——
    没有 key、只有英文、也不说是哪一格。留空不归这里管:没填是合法的,缺省值是节点自己的事。
    """

    fields = (NODE_TYPES.get(node_type) or {}).get("config") or {}
    for key, spec in fields.items():
        if spec.get("type") != "number" or key not in config:
            continue
        value = config[key]
        if value is None or isinstance(value, (int, float)):
            continue
        if isinstance(value, str):
            if not value.strip():
                continue
            try:
                float(value)
                continue
            except ValueError:
                pass
        raise WorkflowDomainError("wfErr_mustBeNumber", params={"field": field_name(key, spec)})
    return config


def one_asset_fields(node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """只收**一份**素材的字段(`asset_id`、`audio_asset_id`…),插值、绑定之后收到的是一串时:一份就是它;好几份不替人挑,
    报出来说清两种接法(只要一份就改接上游只交一份的口;每一份都要就放进循环)。

    一串从哪来:上游一次交好几份素材的口 —— 宫格切分的 `asset_ids`、一次出两张的 ComfyUI 工作流那个保存节点的口
    (见 plugins.tools._collect_artifact)。此前一串原样交给执行器,`str()` 成 "['…', '…']",报的是「素材不在这个工作区」,
    看不出是接错了口。收一串的字段(`asset_ids`,按名字认,和 config_data_type 同一套命名)照收。插件节点的入参在
    plugins.inputs.materialize 按同一条规矩查(那边按 input_schema 认一份还是一串)。
    """

    fields = (NODE_TYPES.get(node_type) or {}).get("config") or {}
    for key, spec in fields.items():
        value = config.get(key)
        if not isinstance(value, list) or config_data_type(key, spec) != "asset":
            continue
        if key == "asset_ids" or key.endswith("_asset_ids"):
            continue
        refs = [str(one) for one in value if one not in (None, "")]
        if len(refs) > 1:
            raise WorkflowDomainError("wfErr_oneAssetGotMany", params={"field": field_name(key, spec), "count": len(refs)})
        config[key] = refs[0] if refs else ""
    return config


def interpolate_node_config(
    node_type: str, config: dict[str, Any], context: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """按节点类型插值 config:内嵌子图节点(循环体 / subgraph)的 body/output/condition 保留原文;
    **代码字段(`"type": "code"`)也保留原文**;声明了 `"interpolate": "json"` 的字段按 JSON 的规矩插值
    (见 interpolate_json_text);其余全量插值。

    代码字段不插值:`{{上游.输出}}` 是按文字拼进代码的,上游交来一段带引号的文字就能改写整段脚本
    (「执行脚本」在用户已登录的网页里跑)。上游的值走节点的入参(`input`),作为数据交进去。
    """

    specs = (NODE_TYPES.get(node_type) or {}).get("config") or {}
    as_json = {
        key: config.pop(key)
        for key, spec in specs.items()
        if isinstance(spec, dict) and spec.get("interpolate") == "json" and isinstance(config.get(key), str)
    }
    kept = set(NESTED_BODY_RAW_KEYS) if node_type in NESTED_BODY_TYPES else set()
    kept |= {key for key, spec in specs.items() if isinstance(spec, dict) and spec.get("type") == "code"}
    raw = {key: config.pop(key) for key in list(config) if key in kept}
    config = interpolate(config, context)
    config.update(raw)
    config.update({key: interpolate_json_text(value, context) for key, value in as_json.items()})
    return config


#: 声明成这几类的输出**不可能**是素材(见 node_types.output_data_type):引用它不算「要模型看的图」。
#: 这是给引用画的一道线,不是给值看的 —— 值那边还有一道(解析出来必须真是一张本工作区的素材)。
_NOT_ASSETS = frozenset({"text", "number", "json", "sequence", "scene"})


def _raw_references(value: Any) -> list[str]:
    """一段**还没插值**的模板(config 里存的那份原文)里出现的每一处引用,按出现顺序:`["图.asset_id"]`。

    只认原文,不认插值结果:插值之后 `{{图.asset_id}}` 就成了一串十六进制,和用户手打进去的一串
    id 再也分不开 —— 而「引用即发送」说的是**引用**。
    """
    if isinstance(value, dict):
        return [ref for one in value.values() for ref in _raw_references(one)]
    if isinstance(value, list):
        return [ref for one in value for ref in _raw_references(one)]
    if not isinstance(value, str):
        return []
    return [match.group(1).strip() for match in VARIABLE_RE.finditer(value)]


def _referenced_ids(value: Any) -> list[str]:
    """一处引用解析出来的值里,哪些像素材 id:本身是一串,或是列表里的字符串元素。"""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [one.strip() for one in value if isinstance(one, str) and one.strip()]
    return []


def _source_lines(value: Any) -> list[str]:
    """一行一项的素材字段(`source_assets`)现在的那几行,**原样** —— 顺序就是发给模型的顺序。"""
    if isinstance(value, list):
        return [str(one).strip() for one in value if str(one or "").strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split("\n") if part.strip()]
    return []


def _line_asset_ids(lines: list[str]) -> list[str]:
    """一行一项的素材字段里现在的那几份素材 id(每行 `素材id` 或 `素材id:角色`)。

    和唯一的那份读法(generation.operations.parse_source_assets)同一条:**从右边**切,后半段真是一个
    角色名时才算角色 —— 模板串自己带冒号(`{{图.a:b}}`)不能被腰斩。这里只要 id 那一半:判
    「这一份已经在里面了,不要并第二遍」。
    """

    out: list[str] = []
    for line in lines:
        head, sep, tail = line.rpartition(":")
        out.append(head.strip() if sep and tail.strip() in SOURCE_ROLE_LABELS else line)
    return out


def _role_overrides(value: Any) -> dict[str, str]:
    """`<那一格>_roles`:用户把自动来的哪一条引用改成了什么角色(一条一个 `引用路径:角色`)。"""

    entries = value if isinstance(value, list) else [value]
    out: dict[str, str] = {}
    for entry in entries:
        head, sep, tail = str(entry or "").strip().rpartition(":")
        if sep and head.strip() and tail.strip() in SOURCE_ROLE_LABELS:
            out[head.strip()] = tail.strip()
    return out


def _generation_source_role(db: Any, config: dict[str, Any], role: str) -> bool:
    """生成节点那一格的能力闸:这个模型认不认这个素材角色(见 generation.operations.takes_source_role)。

    问的是节点上写的连接身份 / provider / model / kind 那几格;模型名本身可能来自上游 —— 引擎传进来的
    config 已经插过值、绑过数据边,所以这里问的就是**这一次真的要用的那个模型**。
    """

    provider = str(config.get("provider") or "").strip()
    model = str(config.get("model") or "").strip()
    if not provider or not model:
        return False
    return takes_source_role(
        db,
        provider=provider,
        model=model,
        kind=str(config.get("kind") or "image").strip() or "image",
        provider_profile_id=str(config.get("provider_profile_id") or "").strip() or None,
        role=role,
    )


#: `ref_assets_gate` 点名的能力闸:**注入之前先问一句「这个模型收不收这个角色」**。
#: 判据是既有的那一套(生成描述符的参数面 + 连接上声明的档案,见 generation.operations),和生成漏斗、
#: 界面上的角色格子是同一个答案。生成节点那一格必须有闸:那里「以什么角色发」由模型能力决定,塞错了
#: 就是一次报错或者一次白花钱的生成(大模型节点那一格没有闸 —— 那边只是多带一张图,代价不同)。
REF_ASSET_GATES = {"generation_source_role": _generation_source_role}


def _gate_accepts(gate: Any, db: Any, config: dict[str, Any], role: str, cache: dict[str, bool]) -> bool:
    """问一次闸,同一个角色只问一次(一次运行里会问到的角色就那么几个)。"""
    if role not in cache:
        cache[role] = bool(gate and gate(db, config, role))
    return cache[role]


def with_referenced_assets(
    db: Any,
    workspace_id: str,
    node_type: str,
    raw: dict[str, Any],
    config: dict[str, Any],
    context: dict[str, dict[str, Any]],
    node_types: dict[str, str],
) -> dict[str, Any]:
    """把 `prompt` / `system` 里**引用到的**素材并进声明了 `ref_assets_from` 的那一格。

    维护者的话:「对这种通过 `@` 引用了图片素材的 LLM 节点,其中的『要模型看的图片』**应该自动同步**」。
    此前那段话只是文字:`{{画图.asset_id}}` 插值成一串素材编号,模型从没见过那张图 —— 用户得记得
    再去「要模型看的图片」里手动挑一遍同一张图,忘了就是个安静的错(模型答得像没看图)。
    「AI 生成素材」节点上是同一个断层、同一句话:提示词里引用到的图以**参考图**并进「输入素材」。

    **推导在运行时做,不在保存时同步。** 值到这一刻才知道(上游可能还没跑),而 config 是用户存的:
    保存时同步意味着**老图**(config 里没有那一串 id)照旧看不到图,于是得再补一条「config 里没有
    就现推」的分支 —— 那正是同一条语义写两遍。这里只写一遍:**引用即发送**。

    并进来的怎么排:手动挑的在前(用户排的顺序说了算),引用来的按 prompt → system、按引用出现的
    先后接在后面,同一份素材只发一次。
    `ref_assets_from` 点名的每一格配一条排除清单(`<那一格>_excluded`,一条一个引用路径或素材 id):
    用户删掉一张自动来的图就写在那里 —— 删掉就是删掉,下一轮不再塞回来。

    **一行一项的那一格多两样**(`ref_assets_role`:生成节点的「输入素材」,每行 `素材:角色`):

    - 并进来的每一份都带**角色**,默认是声明里写的那个,用户改过的那几条记在 `<那一格>_roles`
      (`引用路径:角色`)里 —— 角色不同,结果不同(首帧 / 参考图 / 驱动音频是三条路);
    - `ref_assets_gate` 点名的**能力闸**先问一句「这个模型收不收这个角色」。**不收就不并**(硬塞换来
      一次提交期报错,或者一次白花钱的生成),但也不沉默 —— 界面上明说(见 referencedImages 那一行)。

    不是素材的引用**跳过**,不报错也不硬塞:提示词里引用的多半是文字(`{{llm.text}}`)、也可能是一段
    视频。视频当参考图发出去只会当场 400,把整条工作流拦下来,而用户的提示词本身没有任何问题。
    """

    specs = (NODE_TYPES.get(node_type) or {}).get("config") or {}
    declared = [
        (key, spec) for key, spec in specs.items() if isinstance(spec, dict) and spec.get("ref_assets_from")
    ]
    if not declared:
        return config
    resolved = dict(config)
    for key, spec in declared:
        sources = [name for name in (spec.get("ref_assets_from") or []) if isinstance(name, str)]
        media = config_media(spec)
        excluded = set(id_list(resolved.get(f"{key}_excluded")))
        #: 一行一项的素材字段(声明了 `ref_assets_role`):并进来时每一份都要带角色。
        default_role = str(spec.get("ref_assets_role") or "").strip()
        pinned = _role_overrides(resolved.get(f"{key}_roles")) if default_role else {}
        picked_lines = _source_lines(resolved.get(key)) if default_role else id_list(resolved.get(key))
        picked = _line_asset_ids(picked_lines) if default_role else list(picked_lines)
        gate = REF_ASSET_GATES.get(str(spec.get("ref_assets_gate") or ""))
        accepted: dict[str, bool] = {}
        added: list[str] = []
        added_ids: set[str] = set()
        for source in sources:
            for ref in _raw_references(raw.get(source)):
                if ref in excluded:
                    continue
                node_id, _, output = ref.partition(".")
                if not output:
                    continue
                #: 引用的那个输出不可能装素材(`{{llm.text}}`)就不用往下解析了 —— 它本来就只是文字。
                if output_data_type(output, NODE_TYPES.get(node_types.get(node_id, "")) or {}) in _NOT_ASSETS:
                    continue
                role = pinned.get(ref, default_role)
                #: 能力闸:这个模型不收这个角色就不并 —— 不硬塞,也不在这里沉默(界面会说)。
                if role and not _gate_accepts(gate, db, resolved, role, accepted):
                    continue
                for candidate in _referenced_ids(interpolate("{{" + ref + "}}", context)):
                    if candidate in excluded or candidate in picked or candidate in added_ids:
                        continue
                    asset = db.get(Asset, candidate)
                    #: 不在这个工作区、已经删了:跳过。
                    if asset is None or asset.workspace_id != workspace_id:
                        continue
                    if role:
                        #: 角色说了要哪一种素材(`reference_image` 要一张图):不是那一种就跳过。
                        if SOURCE_ROLE_MEDIA.get(role) != asset.kind:
                            continue
                    elif media and asset.kind not in media:
                        continue
                    added.append(f"{candidate}:{role}" if role else candidate)
                    added_ids.add(candidate)
        if not added:
            continue
        merged = [*picked_lines, *added]
        if isinstance(resolved.get(key), str):
            resolved[key] = "\n".join(merged) if default_role else ",".join(merged)
        else:
            resolved[key] = merged
    return resolved
