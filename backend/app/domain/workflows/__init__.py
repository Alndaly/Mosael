"""工作流内核(Coze/Dify 式)。

一个工作流 = 节点(nodes) + 连线(edges) 的 DAG,存为 JSON graph:

    {
      "nodes": [{"id": "n1", "type": "start", "name": "开始",
                  "position": {"x": 0, "y": 0}, "config": {...}}, ...],
      "edges": [{"id": "e1", "source": "n1", "target": "n2"}, ...]
    }

节点 config 里的字符串支持 `{{节点id.输出名}}` 变量引用,执行时按拓扑序
求值。定时任务与智能体都以工作流为执行单元。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Workflow


class WorkflowDomainError(RuntimeError):
    pass


# 节点类型注册表:同时驱动后端校验、前端节点面板和智能体的图编辑提示。
# outputs 是节点执行后写入上下文的键;config 描述每个可配置字段。
NODE_TYPES: dict[str, dict[str, Any]] = {
    "start": {
        "label": "开始",
        "description": "工作流入口,声明输入参数(运行时可覆盖默认值)。",
        "config": {"params": {"type": "object", "description": "输入参数名 → 默认值"}},
        "outputs": ["*params"],
    },
    "llm": {
        "label": "LLM 生成",
        "description": "调用配置的 AI 供应商生成文本。",
        "config": {
            "prompt": {"type": "template", "required": True, "description": "用户提示词,支持 {{变量}}"},
            "system": {"type": "template", "description": "系统提示词"},
            "preset": {
                "type": "string",
                "description": "生成风格(替代裸 temperature)",
                "options": ["precise", "balanced", "creative"],
            },
            "profile_id": {"type": "string", "description": "供应商配置 id,留空自动选择"},
            "model": {"type": "string", "description": "模型名,留空用配置默认"},
            "temperature": {"type": "number", "description": "采样温度 0-2;留空跟随生成风格"},
            "top_p": {"type": "number", "description": "核采样 0-1;留空不传"},
            "max_tokens": {"type": "number", "description": "最大输出 token;留空不传"},
            "frequency_penalty": {"type": "number", "description": "频率惩罚 -2 到 2;留空不传"},
            "presence_penalty": {"type": "number", "description": "存在惩罚 -2 到 2;留空不传"},
            "seed": {"type": "number", "description": "随机种子;留空不传"},
            "stop": {"type": "string", "description": "停止词,多个用换行分隔"},
            "response_format": {
                "type": "string",
                "description": "输出格式",
                "options": ["text", "json_object", "json_schema"],
            },
            "json_schema_name": {"type": "string", "description": "JSON Schema 名称,默认 workflow_output"},
            "json_schema": {"type": "object", "description": "JSON Schema;仅 response_format=json_schema 时使用"},
            "json_schema_strict": {
                "type": "string",
                "description": "JSON Schema 严格模式",
                "options": ["true", "false"],
            },
        },
        "outputs": ["text", "json"],
    },
    "kb_search": {
        "label": "知识库检索",
        "description": "检索指定知识库,输出片段文本。",
        "config": {
            "dataset_id": {"type": "string", "description": "选择要检索的知识库(留空则用工作区内首个)"},
            "query": {"type": "template", "required": True},
            "limit": {"type": "number", "description": "返回条数,默认 5"},
        },
        "outputs": ["text", "results"],
    },
    "plugin_tool": {
        "label": "插件工具",
        "description": "调用已启用插件的纯函数工具。",
        "config": {
            "plugin_id": {"type": "string", "required": True},
            "tool_name": {"type": "string", "required": True},
            "input": {"type": "object", "description": "工具入参,值支持 {{变量}}"},
        },
        "outputs": ["output"],
    },
    "transcribe_asset": {
        "label": "素材转写",
        "description": "对音视频素材跑 ASR,输出全文。",
        "config": {"asset_id": {"type": "template", "required": True}},
        "outputs": ["text"],
    },
    "export_sequence": {
        "label": "导出时间线",
        "description": "渲染导出一条时间线,产出新素材。",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["asset_id"],
    },
    "ai_generate": {
        "label": "AI 生成素材",
        "description": "文生图/文生视频,产出素材进素材库。",
        "config": {
            "provider": {"type": "string", "required": True},
            "model": {"type": "string", "required": True},
            "kind": {"type": "string", "required": True, "description": "生成类型", "options": ["image", "video"]},
            "prompt": {"type": "template", "required": True},
        },
        "outputs": ["asset_id", "generation_id"],
    },
    "publish": {
        "label": "发布",
        "description": "用已登录的平台账号发布到抖音 / 小红书 / 视频号 / B站(由桌面端内嵌浏览器执行)。",
        "config": {
            "account_id": {"type": "string", "required": True, "description": "发布账号 id(浏览器池可查)"},
            "asset_id": {"type": "template", "required": True},
            "title": {"type": "template"},
            "description": {"type": "template"},
        },
        "outputs": ["result"],
    },
    "condition": {
        "label": "条件分支",
        "description": "按条件把流程导向「真」或「假」分支(连线时从对应端点拉出)。",
        "config": {
            "left": {"type": "template", "required": True, "description": "左值,如 {{llm-1.text}}"},
            "op": {
                "type": "string",
                "required": True,
                "description": "比较方式",
                "options": ["equals", "not_equals", "contains", "not_contains", "empty", "not_empty", "gt", "lt"],
            },
            "right": {"type": "template", "description": "右值(empty/not_empty 不需要)"},
        },
        "outputs": ["result"],
        "branches": ["true", "false"],
    },
    "http_request": {
        "label": "HTTP 请求",
        "description": "调用外部 API,输出状态码与响应内容。",
        "config": {
            "method": {"type": "string", "description": "默认 GET", "options": ["GET", "POST", "PUT", "DELETE"]},
            "url": {"type": "template", "required": True},
            "headers": {"type": "object", "description": "请求头,值支持 {{变量}}"},
            "body": {"type": "template", "description": "请求体(POST/PUT),JSON 或纯文本"},
        },
        "outputs": ["status", "text", "json"],
    },
    "code": {
        "label": "代码",
        "description": "运行一段 Python:inputs 为入参 dict,把结果赋给 output 变量。与插件同级的本地信任沙箱。",
        "config": {
            "code": {"type": "code", "required": True, "description": "如:output = len(inputs['text'])"},
            "input": {"type": "object", "description": "入参,值支持 {{变量}}"},
        },
        "outputs": ["output"],
    },
    "template": {
        "label": "文本模板",
        "description": "把多个上游变量拼装成一段文本。",
        "config": {"template": {"type": "template", "required": True}},
        "outputs": ["text"],
    },
    "json_extract": {
        "label": "JSON 提取",
        "description": "从 JSON/对象里按点路径取值,常接在 HTTP 请求或插件工具后面。",
        "config": {
            "source": {"type": "template", "required": True, "description": "JSON 文本或 {{节点.json}}"},
            "path": {"type": "string", "description": "点路径,如 data.items.0.title;留空返回整个对象"},
        },
        "outputs": ["value", "text"],
    },
    "text_transform": {
        "label": "文本处理",
        "description": "对文本做去空白/大小写/替换/正则提取/取长度等处理。",
        "config": {
            "text": {"type": "template", "required": True},
            "op": {
                "type": "string",
                "required": True,
                "description": "处理方式",
                "options": ["trim", "upper", "lower", "replace", "regex_extract", "length"],
            },
            "find": {"type": "string", "description": "replace 的查找串 / regex_extract 的正则"},
            "replace": {"type": "string", "description": "replace 的替换串"},
        },
        "outputs": ["text", "length"],
    },
    "delay": {
        "label": "延时",
        "description": "等待若干秒再继续(限流/节流用)。",
        "config": {"seconds": {"type": "number", "description": "等待秒数,默认 1,上限 300"}},
        "outputs": ["waited"],
    },
    "synthesize_speech": {
        "label": "语音合成",
        "description": "用指定音色把文本合成为配音,产出音频素材进素材库。",
        "config": {
            "voice_id": {"type": "string", "required": True, "description": "音色 id(配音库可查)"},
            "text": {"type": "template", "required": True},
        },
        "outputs": ["asset_id"],
    },
    "notify": {
        "label": "发送通知",
        "description": "给工作区成员推送一条站内通知。",
        "config": {
            "title": {"type": "template", "required": True},
            "body": {"type": "template", "description": "通知正文"},
        },
        "outputs": ["sent"],
    },
    "translate": {
        "label": "翻译",
        "description": "把文本翻译成目标语言:Google 免费接口(无需 key)或 AI 供应商。",
        "config": {
            "text": {"type": "template", "required": True},
            "target_lang": {
                "type": "string",
                "required": True,
                "description": "目标语言",
                "options": ["en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "ru"],
            },
            "engine": {"type": "string", "description": "翻译引擎(默认 Google 免费)", "options": ["google", "ai"]},
            "profile_id": {"type": "string", "description": "engine=ai 时的供应商配置,留空自动"},
        },
        "outputs": ["text"],
    },
    "loop_foreach": {
        "label": "循环·遍历",
        "category": "组合",
        "description": "对一个列表逐项运行内嵌子流程,汇总每次迭代的输出为列表。子流程内用 {{loop.item}} / {{loop.index}} 引用当前元素与序号。",
        "config": {
            "items": {
                "type": "template",
                "required": True,
                "description": "要遍历的列表,支持 {{变量}}(如 {{split_1.results}});也接受多行文本(按行拆分)",
            },
            "body": {"type": "graph", "description": "循环体子流程(在节点内编辑;子流程节点用 {{loop.item}}/{{loop.index}})"},
            "output": {
                "type": "template",
                "description": "每次迭代的输出,引用子流程节点输出(如 {{translate_1.text}});留空则输出整份子上下文",
            },
        },
        "outputs": ["results", "count"],
    },
    "loop_while": {
        "label": "循环·条件",
        "category": "组合",
        "description": "反复运行内嵌子流程,直到条件不再成立(带最大次数上限防死循环)。子流程内用 {{loop.index}} 拿当前轮次;子流程里放一个「条件」节点,把它的 {{节点id.result}} 填到 condition。",
        "config": {
            "body": {"type": "graph", "description": "循环体子流程(每轮跑一遍;通常含一个条件节点决定是否继续)"},
            "condition": {
                "type": "template",
                "description": "每轮跑完后判断是否继续,引用子流程里条件节点的布尔输出(如 {{check.result}});留空则只跑一轮",
            },
            "max_iterations": {"type": "number", "description": "最大轮次(默认 50,硬上限 1000),防死循环"},
            "output": {"type": "template", "description": "每轮的输出(如 {{step.text}});留空则输出整份子上下文"},
        },
        "outputs": ["results", "count", "iterations"],
    },
    "asset_query": {
        "label": "素材筛选",
        "description": "按条件批量选出工作区里的素材(类型/名称/标签),输出素材列表 —— 常接「循环·遍历」的 items 逐个处理。",
        "config": {
            "kind": {"type": "string", "description": "素材类型", "options": ["all", "video", "image", "audio"]},
            "name_contains": {"type": "template", "description": "名称包含此关键词(留空不筛)"},
            "tags": {"type": "template", "description": "标签(逗号分隔,命中任一即选;留空不筛)"},
            "limit": {"type": "number", "description": "最多返回条数(默认 50,上限 500)"},
        },
        "outputs": ["assets", "ids", "count"],
    },
    "asset_tag": {
        "label": "素材打标签",
        "description": "给素材增删标签 —— 常接「素材筛选」或「循环·遍历」,把整理归档做成一步。",
        "config": {
            "asset_ids": {
                "type": "template",
                "required": True,
                "description": "素材 id(逗号分隔,或直接接「素材筛选」的 ids)",
            },
            "tags": {"type": "template", "required": True, "description": "标签(逗号分隔)"},
            "mode": {
                "type": "string",
                "description": "add=追加,remove=移除,replace=整组替换",
                "options": ["add", "remove", "replace"],
            },
        },
        "outputs": ["updated", "count"],
    },
    "asset_update": {
        "label": "素材整理",
        "description": "重命名素材、或把素材归入某个项目。",
        "config": {
            "asset_ids": {"type": "template", "required": True, "description": "素材 id(逗号分隔)"},
            "name": {"type": "template", "description": "新名称;多个素材时会自动加序号。留空则不改名"},
            "project_id": {"type": "template", "description": "归入的项目 id;留空则不改动归属"},
        },
        "outputs": ["updated", "count"],
    },
    "project_create": {
        "label": "新建项目",
        "description": "在当前工作区建一个项目,输出它的 id —— 可接「素材整理」把素材归进去。",
        "config": {
            "name": {"type": "template", "required": True, "description": "项目名"},
        },
        "outputs": ["project_id", "name"],
    },
    # 组合/嵌套:把工作流当子流程调用,声明工作流的输出契约。
    "call_workflow": {
        "label": "调用工作流",
        "category": "组合",
        "description": "把另一个已保存的工作流当子流程调用:映射入参 → 跑完取其「输出」节点声明的结果作为本节点输出(引用 {{call_1.output.xxx}})。子流程走完整引擎,自动收纳到本流程下、随本流程取消;防递归、防过深。",
        "config": {
            "workflow_id": {"type": "string", "required": True, "description": "要调用的工作流(选一个已保存的)"},
            "inputs": {"type": "object", "description": "入参映射 {参数名: 值/引用},喂给子流程开始节点的参数,如 {\"topic\": \"{{start.theme}}\"}"},
        },
        "outputs": ["output"],
    },
    "output": {
        "label": "输出",
        "category": "组合",
        "description": "声明本工作流的输出(参考 dify End):{名: 引用}。被「调用工作流」时,调用方拿到的就是这里声明的具名输出;留空/无本节点则输出整份上下文。",
        "config": {
            "values": {"type": "object", "description": "具名输出 {名: 引用},如 {\"result\": \"{{llm_1.text}}\", \"url\": \"{{browser_1.value}}\"}"},
        },
        "outputs": ["output"],
    },
    "subgraph": {
        "label": "子图",
        "category": "组合",
        "description": "把一组节点封装成一个可复用子图(参考 ComfyUI「折叠为子图」):内嵌、可任意嵌套,在节点内进子画布编辑。与主引擎同一套内核(并行/条件分支一致)。用 inputs 把外层值喂进去(子图内 {{input.名}} 引用),output 指定子图输出(引用内部节点,如 {{node_1.text}});留空则输出整份子上下文。",
        "config": {
            "inputs": {"type": "object", "description": "喂进子图的输入 {名: 值/引用},子图内用 {{input.名}} 取,如 {\"topic\": \"{{start.theme}}\"}"},
            "body": {"type": "graph", "description": "子图(在节点内进子画布编辑;无入边的根即入口,可放多个)"},
            "output": {"type": "template", "description": "子图输出,引用内部节点输出(如 {{node_1.text}});留空则输出整份子上下文"},
        },
        "outputs": ["output"],
    },
    # 浏览器自动化(RPA):在隔离浏览器会话里自动化操作网页,与发布登录完全隔离。
    # 典型链路:打开浏览器 → 导航/点击/输入/等待 → 提取 → 关闭。session 输出串起整条链。
    "browser_open": {
        "label": "打开浏览器",
        "category": "浏览器",
        "description": "新建一个浏览器会话并可选导航到网址,输出 session 供后续浏览器节点使用。ephemeral=临时(跑完即清);named=具名持久(保留登录);pool=复用「浏览器池」里某个已登录档案(受租约:一档案一时刻一会话)。",
        "config": {
            "url": {"type": "template", "description": "打开后导航到的网址(可留空,之后用「导航」节点)"},
            "session_mode": {"type": "string", "options": ["ephemeral", "named", "pool"], "description": "ephemeral=临时;named=具名持久;pool=复用浏览器池档案(已登录身份)"},
            "session_name": {"type": "string", "description": "具名会话名称(session_mode=named 时必填)"},
            "profile_id": {"type": "string", "description": "浏览器池档案(session_mode=pool 时必填),复用其登录态"},
        },
        "outputs": ["session"],
    },
    "browser_navigate": {
        "label": "浏览器·导航",
        "category": "浏览器",
        "description": "在会话里跳转到网址。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "url": {"type": "template", "required": True, "description": "目标网址"},
        },
        "outputs": ["session"],
    },
    "browser_click": {
        "label": "浏览器·点击",
        "category": "浏览器",
        "description": "按 CSS 选择器或可见文本点击元素。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "selector": {"type": "template", "description": "CSS 选择器(与文本二选一)"},
            "text": {"type": "template", "description": "按可见文本点击(与选择器二选一)"},
            "exact": {"type": "string", "options": ["否", "是"], "description": "文本是否精确匹配"},
        },
        "outputs": ["session"],
    },
    "browser_input": {
        "label": "浏览器·输入",
        "category": "浏览器",
        "description": "往输入框/文本域填入内容(含 contenteditable)。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "selector": {"type": "template", "required": True, "description": "目标输入框的 CSS 选择器"},
            "value": {"type": "template", "description": "要填入的内容"},
        },
        "outputs": ["session"],
    },
    "browser_upload": {
        "label": "浏览器·上传文件",
        "category": "浏览器",
        "description": "往页面的文件输入框(<input type=file>)塞一个本地文件——发布上传视频的关键一步。用 asset_id 传素材(如 {{export_1.asset_id}}),或 file_path 传本地绝对路径(二选一)。走 CDP setFileInputFiles,不弹系统对话框。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "selector": {"type": "template", "description": "文件输入框 CSS 选择器(默认 input[type=file])"},
            "asset_id": {"type": "template", "description": "要上传的素材 id(如 {{export_1.asset_id}});与 file_path 二选一"},
            "file_path": {"type": "template", "description": "或直接给本地绝对路径;与 asset_id 二选一"},
            "timeout_ms": {"type": "string", "description": "等文件输入框出现的超时(毫秒,默认 15000)"},
        },
        "outputs": ["session"],
    },
    "browser_extract": {
        "label": "浏览器·提取",
        "category": "浏览器",
        "description": "取元素的文本或属性;可一次取全部匹配。输出 value 供下游使用。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "selector": {"type": "template", "required": True, "description": "CSS 选择器"},
            "attribute": {"type": "string", "description": "取该属性值(留空=取文本)"},
            "all": {"type": "string", "options": ["否", "是"], "description": "是=取全部匹配为数组;否=第一个"},
        },
        "outputs": ["session", "value"],
    },
    "browser_wait": {
        "label": "浏览器·等待",
        "category": "浏览器",
        "description": "等元素出现/消失、URL 变化或页面出现某文本。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "selector": {"type": "template", "description": "等这个元素(默认等出现)"},
            "gone": {"type": "string", "options": ["否", "是"], "description": "是=等元素消失"},
            "url_contains": {"type": "template", "description": "等 URL 包含此片段(与选择器/文本三选一)"},
            "text": {"type": "template", "description": "等页面出现此文本"},
            "timeout_ms": {"type": "number", "description": "超时毫秒,默认 15000"},
        },
        "outputs": ["session"],
    },
    "browser_scroll": {
        "label": "浏览器·滚动",
        "category": "浏览器",
        "description": "滚动到某元素,或按像素滚动页面。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "selector": {"type": "template", "description": "滚动到该元素(留空=按 dy 滚动)"},
            "dy": {"type": "number", "description": "无选择器时向下滚动的像素,默认 600"},
        },
        "outputs": ["session"],
    },
    "browser_evaluate": {
        "label": "浏览器·执行脚本",
        "category": "浏览器",
        "description": "在页面里执行一段 JS 表达式并取返回值(高级)。",
        "config": {
            "session": {"type": "string", "required": True, "description": "来自「打开浏览器」的 session"},
            "expression": {"type": "code", "required": True, "description": "JS 表达式,其返回值即输出 value"},
        },
        "outputs": ["session", "value"],
    },
    "browser_close": {
        "label": "关闭浏览器",
        "category": "浏览器",
        "description": "关闭会话:临时会话顺带清掉 cookie/存储。用完记得关,免得视图常驻。",
        "config": {
            "session": {"type": "string", "required": True, "description": "要关闭的 session"},
        },
        "outputs": [],
    },
}

VARIABLE_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def validate_graph(
    graph: dict[str, Any],
    *,
    require_start: bool = True,
    require_config: bool = True,
    allow_missing_start: bool = False,
) -> list[str]:
    """结构校验:返回错误列表(空表 = 合法)。

    require_config=False 用于**保存**:必填字段缺失属于「还没配完」,不该拦住存盘 —— 否则配合
    实时保存,新加一个带必填项的节点就永远存不下来。缺必填由「就绪检查」提示、由运行时拦截。

    allow_missing_start=True 同样用于**保存**:用户可以把画布清空或删除开始节点做草稿;
    运行时仍然 require_start=True 且 allow_missing_start=False,没有开始节点就不能运行。

    require_start=False 用于循环体子图:子图没有 start 节点(执行时由循环上下文喂入
    {{loop.item}}),无入边的节点即为入口;若子图里出现 start 则报错。
    """
    errors: list[str] = []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["graph 必须包含 nodes 与 edges 两个数组"]
    # Only the CONTAINERS were type-checked. Their elements were assumed to be dicts, so
    # {"nodes": ["oops"]} reached .get() and raised AttributeError straight past the
    # WorkflowDomainError handler — a 500 for what is plainly a bad request. This has to come
    # before the first .get() below, not after.
    if any(not isinstance(node, dict) for node in nodes) or any(not isinstance(e, dict) for e in edges):
        return ["节点与连线必须是对象"]

    # 数据边(kind="data")把上游输出绑到目标输入 → 该输入即便字面量为空也算已满足。
    data_bound: set[tuple[str, str]] = {
        (str(edge.get("target", "")), str(edge.get("target_input", "")))
        for edge in edges
        if str(edge.get("kind", "")) == "data" and edge.get("target_input")
    }

    seen_ids: set[str] = set()
    start_count = 0
    for node in nodes:
        node_id = str(node.get("id", ""))
        node_type = str(node.get("type", ""))
        if not node_id:
            errors.append("存在缺少 id 的节点")
            continue
        if node_id in seen_ids:
            errors.append(f"节点 id 重复: {node_id}")
        seen_ids.add(node_id)
        if node_type not in NODE_TYPES:
            errors.append(f"未知节点类型: {node_type} ({node_id})")
            continue
        if node_type == "start":
            start_count += 1
        if require_config:
            for key, spec in NODE_TYPES[node_type]["config"].items():
                if isinstance(spec, dict) and spec.get("required"):
                    value = (node.get("config") or {}).get(key)
                    if value in (None, "") and (node_id, key) not in data_bound:
                        errors.append(f"节点 {node_id} 缺少必填配置 {key}")
    if require_start:
        if start_count > 1 or (start_count == 0 and not allow_missing_start):
            errors.append(f"工作流必须恰好包含 1 个开始节点(当前 {start_count} 个)")
    elif start_count > 0:
        errors.append("循环体子图不能包含开始节点")

    node_types = {str(node.get("id", "")): str(node.get("type", "")) for node in nodes}
    adjacency: dict[str, list[str]] = {}
    indegree: dict[str, int] = {node_id: 0 for node_id in seen_ids}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in seen_ids or target not in seen_ids:
            errors.append(f"连线引用了不存在的节点: {source} → {target}")
            continue
        handle = edge.get("source_handle")
        if node_types.get(source) == "condition" and handle not in (None, "true", "false"):
            errors.append(f"条件节点的分支端点必须是 true/false: {source}")
        adjacency.setdefault(source, []).append(target)
        indegree[target] = indegree.get(target, 0) + 1

    # Kahn 拓扑排序检环
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    degrees = dict(indegree)
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in adjacency.get(current, []):
            degrees[nxt] -= 1
            if degrees[nxt] == 0:
                queue.append(nxt)
    if seen_ids and visited != len(seen_ids):
        errors.append("工作流包含环路,必须是有向无环图")
    return errors


# 内嵌子图类节点:body/output/condition 属于**内层**作用域(见 binding.interpolate_node_config
# 保留原文的理由),既是插值时机的依据,也是校验时不下钻的依据。binding.py 从这里取,单一真源。
NESTED_BODY_TYPES = frozenset({"loop_foreach", "loop_while", "subgraph"})
NESTED_BODY_RAW_KEYS = ("body", "output", "condition")


def validate_body_graph(body: dict[str, Any], *, scope: str = "loop") -> list[str]:
    """内嵌子图(循环体 / subgraph)校验:必须非空、无 start 节点、其余同 validate_graph;
    再查引用是否越出作用域。scope 是执行时播种的作用域名——循环体用 "loop"、subgraph 用 "input"。"""
    label = "循环体" if scope == "loop" else "子图"
    nodes = body.get("nodes") if isinstance(body, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return [f"{label}不能为空,至少要有一个节点"]
    errors = validate_graph(body, require_start=False)
    errors.extend(_unresolvable_body_refs(nodes, scope))
    return errors


def _unresolvable_body_refs(nodes: list[Any], scope: str) -> list[str]:
    """Reject a body template that references anything outside its own scope.

    A body context is seeded with the scope var (`loop` for loops, `input` for subgraph) and the
    body's own nodes — nothing else. A body node referencing an outer node like {{start.prefix}}
    therefore interpolated to the empty string: no error, no warning, just silently missing text in
    whatever the body produced. That is the worst failure mode available, so name it at validation
    time instead.

    (Making the body actually see the outer scope is not a matter of passing more context: body,
    output and condition are deliberately left un-interpolated at the outer scope so that
    {{loop.item}} / {{input.x}} survive to be resolved when the body runs. Resolving outer
    references there too means a second, guarded pass — a real change, not a tweak.)

    Nested bodies are NOT descended into: a nested loop/subgraph node's own body/output/condition
    belong to *its* inner scope and are validated when it runs. Scanning them here would misreport
    the inner body's node names as out-of-scope references. Its `inputs`/`items` (outer-facing) are
    still scanned, since those resolve in *this* scope.
    """
    known = {scope} | {str(node.get("id", "")) for node in nodes if isinstance(node, dict)}
    unknown: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = dict(node.get("config") or {})
        if node.get("type") in NESTED_BODY_TYPES:
            for key in NESTED_BODY_RAW_KEYS:
                config.pop(key, None)
        for match in VARIABLE_RE.finditer(json.dumps(config, ensure_ascii=False)):
            root = match.group(1).strip().split(".")[0]
            if root and root not in known:
                unknown.add(root)
    if not unknown:
        return []
    if scope == "loop":
        return [f"循环体引用了循环外的节点:{', '.join(sorted(unknown))};循环体只能引用 loop 与体内节点"]
    return [f"子图引用了作用域外的节点:{', '.join(sorted(unknown))};子图只能引用 input 与体内节点"]


# 「能在后端主机上跑任意代码」的节点类型。这类节点的写入权限不是内容权限,而是主机权限:
# code 节点是子进程隔离 + 超时 + 输出上限,但**不是沙箱** —— 里面的 Python 能读写文件系统、
# 发网络请求。单机安装下这无所谓(作者就是机器主人);团队/远程后端下,持有 edit 的 editor
# 本来能存这样一张图,等于把「能改内容」升格成「能拿服务器」。落库入口因此额外要 instance-admin
# (见 api/routes/workflows.py 的 ensure_graph_node_privileges 与 core/permissions.ensure_instance_admin)。
PRIVILEGED_NODE_TYPES = frozenset({"code"})

_MAX_GRAPH_SCAN_DEPTH = 16


def privileged_nodes_in_graph(graph: Any, *, _depth: int = 0) -> set[str]:
    """递归找出图里用到的特权节点类型(含 loop/subgraph 的内嵌体)。

    必须递归:内嵌体是 config["body"] 里的一整张图,只查顶层的话,把 code 节点框选「折叠为子图」
    就能绕过门禁。深度上限只是防御畸形/自引用输入——真实嵌套受 MAX_NEST_DEPTH 约束,远小于它。
    """
    if _depth > _MAX_GRAPH_SCAN_DEPTH or not isinstance(graph, dict):
        return set()
    found: set[str] = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        if ntype in PRIVILEGED_NODE_TYPES:
            found.add(ntype)
        if ntype in NESTED_BODY_TYPES:
            found |= privileged_nodes_in_graph((node.get("config") or {}).get("body"), _depth=_depth + 1)
    return found


def topo_order(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """稳定拓扑序(按 nodes 数组原顺序打破平局)。假定 graph 已通过校验。"""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    indegree = {str(n["id"]): 0 for n in nodes}
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge["source"]), []).append(str(edge["target"]))
        indegree[str(edge["target"])] += 1
    order: list[dict[str, Any]] = []
    by_id = {str(n["id"]): n for n in nodes}
    ready = [str(n["id"]) for n in nodes if indegree[str(n["id"])] == 0]
    while ready:
        current = ready.pop(0)
        order.append(by_id[current])
        for nxt in adjacency.get(current, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return order


def interpolate(value: Any, context: dict[str, dict[str, Any]]) -> Any:
    """把字符串里的 {{node.key}} 换成上下文值;整串引用时保留原类型。"""
    if isinstance(value, dict):
        return {k: interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, context) for v in value]
    if not isinstance(value, str):
        return value

    def lookup(ref: str) -> Any:
        # Walk a dotted path: {{node.key}}, and nested {{loop.item.name}} / {{q.assets.0.id}}.
        parts = ref.split(".")
        if parts[0] not in context:
            # A miss must read as empty, not as the {} sentinel used to walk the path. Returning
            # the dict meant a typo'd `condition` made _truthy({}) false — so a while loop ran
            # exactly once and looked deliberate — while a typo'd `left` with op `not_empty`
            # evaluated TRUE, because str({}) is non-empty. The branch silently inverted.
            return ""
        current: Any = context[parts[0]]
        for part in parts[1:]:
            if isinstance(current, dict):
                current = current.get(part, "")
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return ""
            else:
                return ""
        return current

    whole = VARIABLE_RE.fullmatch(value.strip())
    if whole:
        return lookup(whole.group(1))
    return VARIABLE_RE.sub(lambda m: str(lookup(m.group(1))), value)


def list_workflows(db: Session, workspace_id: str) -> list[Workflow]:
    return list(
        db.scalars(select(Workflow).where(Workflow.workspace_id == workspace_id).order_by(Workflow.updated_at.desc()))
    )


def create_workflow(
    db: Session, *, workspace_id: str, name: str, description: str = "", graph: dict[str, Any] | None = None
) -> Workflow:
    graph = graph if graph is not None else default_graph()
    # 保存放行「还没配完」:必填缺失交给就绪检查与运行时,否则新节点存不下来。
    errors = validate_graph(graph, require_config=False, allow_missing_start=True)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    workflow = Workflow(workspace_id=workspace_id, name=name, description=description, graph=graph)
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def update_workflow(db: Session, workflow: Workflow, changes: dict[str, Any]) -> Workflow:
    if "graph" in changes and changes["graph"] is not None:
        errors = validate_graph(changes["graph"], require_config=False, allow_missing_start=True)
        if errors:
            raise WorkflowDomainError("；".join(errors))
        workflow.graph = changes["graph"]
    if changes.get("name"):
        workflow.name = changes["name"]
    if changes.get("description") is not None:
        workflow.description = changes["description"]
    db.commit()
    db.refresh(workflow)
    return workflow


def default_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 80, "y": 160}, "config": {"params": {}}}
        ],
        "edges": [],
    }
