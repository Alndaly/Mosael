"""格式校验报错的语言,以及「数据自带的多语言文字」怎么挑。

**语言放在一个 ContextVar 里,桌面后端和社区服务用的是同一个变量**(backend 的 `core/i18n` 直接拿
这里的 `CURRENT_LOCALE` 当它自己的那一个)。于是校验报错 `str(exc)` 时说哪种语言,和调用方的其他
报错一样由「这一次是谁在问」决定,不需要谁往这里注册回调。

这里的错误只说**是哪一种**(`key`)和参数,句子在 `MESSAGES` 里 —— 和 backend 的 LocalizedError
同一个做法。这些 key 由本包拥有:backend 把 `MESSAGES` 并进它自己的表(所以 `t()`、
`LocalizedError.relay` 认得它们),不在那边再抄一份。
"""

from __future__ import annotations

from contextvars import ContextVar
from string import Formatter
from typing import Any

#: 支持的语言。第一个是缺省。
LOCALES = ("zh", "en")
DEFAULT_LOCALE = LOCALES[0]

#: 这一次是谁在问。没有请求上下文(后台线程、命令行)时取缺省。
CURRENT_LOCALE: ContextVar[str] = ContextVar("mosael_locale", default=DEFAULT_LOCALE)


def current_locale() -> str:
    return CURRENT_LOCALE.get()


#: key → {语言: 文案}。每个 key 两种语言都要有(tests/test_i18n.py)。
MESSAGES: dict[str, dict[str, str]] = {
    # ---- 插件清单 ----
    "pluginErr_manifestMissingField": {
        "zh": "插件清单 {path} 缺少必填字段: {field}",
        "en": "Plugin manifest {path} is missing a required field: {field}",
    },
    "pluginErr_manifestBadId": {
        "zh": "插件清单 {path} 的 id「{id}」不合法:只能用字母、数字和 . _ -,并以字母或数字开头",
        "en": "Plugin manifest {path} has an invalid id “{id}”: use only letters, digits and . _ -, starting with a letter or digit.",
    },
    "pluginErr_manifestBadToolName": {
        "zh": "插件清单 {path} 的工具名「{tool}」不合法:以字母开头,只能用字母、数字、_ 和 -,最长 64 个字符",
        "en": "Plugin manifest {path} has an invalid tool name “{tool}”: start with a letter and use only letters, digits, _ and -, up to 64 characters.",
    },
    "pluginErr_manifestDuplicateTool": {
        "zh": "插件清单 {path} 里有两个工具都叫 {tool}",
        "en": "Plugin manifest {path} declares two tools named {tool}.",
    },
    "pluginErr_manifestReservedKey": {
        "zh": "插件清单 {path}:配置 / 凭据的键 {field} 会盖掉宿主给插件的环境变量(PATH、HOME、LANG、MOSAEL_*、HTTPS_PROXY 这类出站代理变量、PIP_INDEX_URL / npm_config_registry 这类镜像变量等),请换个名字;要装包的镜像就声明 package_sources,由宿主注入",
        "en": "In plugin manifest {path}, the config/credential key {field} would override an environment variable the host provides (PATH, HOME, LANG, MOSAEL_*, outbound proxy variables such as HTTPS_PROXY, mirror variables such as PIP_INDEX_URL / npm_config_registry, and so on); please rename it. For a package mirror, declare package_sources and the host injects it.",
    },
    "pluginErr_manifestPackageSources": {
        "zh": "插件清单 {path}:package_sources 里有认不出的包生态 {value}(认得的:{known})",
        "en": "In plugin manifest {path}, package_sources has an unknown package ecosystem {value} (known: {known}).",
    },
    "pluginErr_manifestDuplicateKey": {
        "zh": "插件清单 {path}:配置 / 凭据的键 {field} 和 {other} 大写后是同一个环境变量",
        "en": "In plugin manifest {path}, the config/credential keys {field} and {other} become the same environment variable once upper-cased.",
    },
    "pluginErr_manifestToolExtraCapability": {
        "zh": "插件清单 {path} 的工具 {tool} 声明了包上没有的能力: {capabilities}",
        "en": "In plugin manifest {path}, tool {tool} declares capabilities the package doesn't: {capabilities}",
    },
    "pluginErr_manifestBadEffects": {
        "zh": "插件清单 {path}:{tool} 的 effects 只能是 {allowed} 之一,写的是「{value}」",
        "en": "In plugin manifest {path}, the effects of {tool} must be one of {allowed}, not “{value}”.",
    },
    "pluginErr_manifestReadOnlyEffects": {
        "zh": "插件清单 {path}:工具 {tool} 标了 read_only,effects 却写成「{value}」—— 只读的工具没有后果,两处说的不是一回事",
        "en": "In plugin manifest {path}, tool {tool} is marked read_only yet declares effects “{value}”; a read-only tool has no effects, so the two contradict each other.",
    },
    "pluginErr_manifestCapabilityNeedsProcess": {
        "zh": "插件清单 {path}:能力 {capability} 只能由本地脚本形态的插件提供(MCP 插件不支持)",
        "en": "In plugin manifest {path}, the {capability} capability can only be provided by a local-script plugin (not MCP).",
    },
    "pluginErr_manifestCapabilityUnclaimed": {
        "zh": "插件清单 {path} 声明了能力 {capability},但没有哪个工具认领它 —— 在负责它的那个工具上也写上 provides",
        "en": "Plugin manifest {path} declares the {capability} capability, but no tool claims it — add provides to the tool that handles it.",
    },
    "pluginErr_manifestCapabilityClaimedTwice": {
        "zh": "插件清单 {path}:能力 {capability} 被多个工具同时认领({tools}),只能有一个",
        "en": "In plugin manifest {path}, the {capability} capability is claimed by several tools ({tools}); only one may claim it.",
    },
    "pluginErr_manifestCapabilityContract": {
        "zh": "插件清单 {path}:工具 {tool} 认领了能力 {capability},入参 {field} 要写成 {expected} —— 宿主的入口和智能体、工作流调的是同一个工具,形状只有一种",
        "en": "In plugin manifest {path}, tool {tool} claims the {capability} capability, so its input {field} must be {expected}; the host's own entry points and agents or workflows call the same tool with the same shape.",
    },
    "pluginErr_manifestBadAudioPrepare": {
        "zh": "插件清单 {path}:工具 {tool} 的入参 {field} 写了 x-audio「{value}」,只认 original(原采样率)或 speech(16k 单声道)",
        "en": "In plugin manifest {path}, input {field} of tool {tool} sets x-audio to “{value}”; only original (source sample rate) or speech (16 kHz mono) are allowed.",
    },
    "pluginErr_manifestNodeAssetNotInSchema": {
        "zh": "插件清单 {path}:工具 {tool} 的 node.config 把 {field} 标成了素材,input_schema 里它却不是 —— 素材要在 input_schema 里标(\"format\": \"asset\"),运行时只看那里",
        "en": "In plugin manifest {path}, tool {tool} marks {field} as an asset in node.config but not in input_schema; mark assets in input_schema (\"format\": \"asset\"), which is what the runtime reads.",
    },
    "pluginErr_manifestSummaryTooLong": {
        "zh": "插件清单 {path}:summary 是一句话,最长 {max} 个字 —— 长的介绍写在第一条技能的 description 里",
        "en": "In plugin manifest {path}, summary is one sentence of at most {max} characters; put a longer introduction in the first skill's description.",
    },
    "pluginErr_manifestServicesShape": {
        "zh": "插件清单 {path}:services 要写成一组 {{\"key\", \"title\", \"tool\"}}",
        "en": "In plugin manifest {path}, services must be a list of {{\"key\", \"title\", \"tool\"}} objects.",
    },
    "pluginErr_manifestServiceBadKey": {
        "zh": "插件清单 {path}:本机服务的 key「{service}」不合法:小写字母开头,只能用小写字母、数字、_ 和 -,最长 40 个字符",
        "en": "In plugin manifest {path}, the local service key “{service}” is invalid: start with a lowercase letter and use only lowercase letters, digits, _ and -, up to 40 characters.",
    },
    "pluginErr_manifestServiceDuplicate": {
        "zh": "插件清单 {path} 里有两种本机服务都叫 {service}",
        "en": "Plugin manifest {path} declares two local services named {service}.",
    },
    "pluginErr_manifestServiceNeedsProcess": {
        "zh": "插件清单 {path}:本机服务 {service} 只能由本地脚本形态的插件声明(MCP 插件不支持)",
        "en": "In plugin manifest {path}, the local service {service} can only be declared by a local-script plugin (not MCP).",
    },
    "pluginErr_manifestServiceUnknownTool": {
        "zh": "插件清单 {path}:本机服务 {service} 的 tool 写的是「{tool}」,清单里没有这个工具",
        "en": "In plugin manifest {path}, the local service {service} names the tool “{tool}”, which the manifest doesn't declare.",
    },
    "pluginErr_manifestServiceNeedsAddress": {
        "zh": "插件清单 {path} 声明了本机服务,instance.config 里就要有一格文本配置叫 {field}:宿主把本机服务的地址写进这一格",
        "en": "Plugin manifest {path} declares a local service, so instance.config needs a text field named {field}: the host writes the local service's address there.",
    },
    # ---- 插件包 ----
    "pluginErr_archiveTooLarge": {
        "zh": "插件包超过大小上限",
        "en": "The plugin package exceeds the size limit.",
    },
    "pluginErr_archiveSymlink": {
        "zh": "插件包里有符号链接,拒绝安装:{name}",
        "en": "The plugin package contains a symbolic link, so it was not installed: {name}",
    },
    "pluginErr_archivePathEscape": {
        "zh": "插件包里有越界路径,拒绝安装:{name}",
        "en": "The plugin package contains a path outside its folder, so it was not installed: {name}",
    },
    "pluginErr_archiveUnpackedTooLarge": {
        "zh": "插件包解压后超过大小上限",
        "en": "The unpacked plugin package exceeds the size limit.",
    },
    "pluginErr_archiveTooManyFiles": {
        "zh": "插件包里的文件太多(上限 {limit} 个)",
        "en": "The plugin package has too many files (the limit is {limit}).",
    },
    "pluginErr_archiveNoManifest": {
        "zh": "这个包里没有 {manifest},不是一个插件",
        "en": "This package has no {manifest}, so it isn't a plugin.",
    },
    "pluginErr_archiveNotZip": {
        "zh": "这不是一个合法的 zip 包",
        "en": "This is not a valid zip file.",
    },
    "pluginErr_manifestInvalid": {
        "zh": "插件清单不合法:{detail}",
        "en": "Invalid plugin manifest: {detail}",
    },
    "pluginErr_skillsInvalid": {
        "zh": "插件带的技能不合格(skills/ 目录):{detail}",
        "en": "A skill bundled with the plugin is invalid (skills/ directory): {detail}",
    },
    # ---- 工作流文件 ----
    "workflowFileErr_notWorkflowFile": {
        "zh": "不是有效的 Mosael 工作流文件",
        "en": "This isn't a valid Mosael workflow file.",
    },
    "workflowFileErr_tooNew": {
        "zh": "文件版本({version})比当前应用支持的更新,请升级应用后再导入",
        "en": "The file version ({version}) is newer than this app supports. Update the app, then import it.",
    },
    "workflowFileErr_badGraph": {
        "zh": "工作流文件里的图不完整:{detail}",
        "en": "The graph in this workflow file is incomplete: {detail}",
    },
    # ---- 画板快照 ----
    "snapshotErr_invalid": {
        "zh": "画板快照不合法:{where} {detail}",
        "en": "Invalid board snapshot: {where} {detail}",
    },
    "snapshotErr_tooManyItems": {
        "zh": "画板快照的格子太多({count} 个,上限 {limit} 个)",
        "en": "The board snapshot has too many items ({count}; the limit is {limit}).",
    },
    # ---- 资产分享包 ----
    "assetBundleErr_invalid": {
        "zh": "资产分享包不合法:{where} {detail}",
        "en": "Invalid asset bundle: {where} {detail}",
    },
    "assetBundleErr_forbiddenKey": {
        "zh": "资产分享包里不能带「{field}」({where}):音色、授权声明原文、关联的 3D 场景 / 模型和本机 id 都不公开",
        "en": "An asset bundle can't carry “{field}” ({where}): voices, consent statements, linked 3D scenes/models and local ids stay private.",
    },
    "assetBundleErr_consentRequired": {
        "zh": "真人人物要先声明授权才能分享:{kinds}",
        "en": "A real person can only be shared with a consent claim: {kinds}",
    },
    "assetBundleErr_consentNotApplicable": {
        "zh": "只有真人人物才需要授权声明",
        "en": "Only a real person takes a consent claim.",
    },
    # ---- 智能体技能(SKILL.md,ADR 0040) ----
    "skillErr_noFrontmatter": {
        "zh": "SKILL.md 第一行要是 ---,下面写 name 和 description,再用一行 --- 收住",
        "en": "SKILL.md must start with a --- line, then name and description, closed by another --- line.",
    },
    "skillErr_frontmatterUnclosed": {
        "zh": "SKILL.md 的头没有收尾:少了结束的那一行 ---",
        "en": "The SKILL.md header is not closed: the ending --- line is missing.",
    },
    "skillErr_missingField": {
        "zh": "SKILL.md 缺少必填字段 {field}",
        "en": "SKILL.md is missing the required field {field}.",
    },
    "skillErr_fieldNotText": {
        "zh": "SKILL.md 的 {field} 要是一段文字",
        "en": "In SKILL.md, {field} must be text.",
    },
    "skillErr_metadataNotStrings": {
        "zh": "SKILL.md 的 metadata 只能是「键: 文字」的映射",
        "en": "In SKILL.md, metadata must map keys to text values.",
    },
    "skillErr_badName": {
        "zh": "技能名「{name}」不合规范:只能用小写英文字母、数字和连字符(-),不能以连字符开头或结尾、不能连着两个,最长 {max} 个字符。中文名写在显示名里",
        "en": "The skill name “{name}” breaks the spec: use lowercase letters, digits and single hyphens, not starting or ending with a hyphen, up to {max} characters. Put a friendly name in the display name.",
    },
    "skillErr_folderMismatch": {
        "zh": "技能文件夹叫「{folder}」,SKILL.md 里的 name 却是「{name}」—— 规范要求两者一样",
        "en": "The skill folder is “{folder}” but SKILL.md says name “{name}”; the spec requires them to match.",
    },
    "skillErr_tooLong": {
        "zh": "SKILL.md 的 {field} 太长了(最多 {max} 个字符)",
        "en": "In SKILL.md, {field} is too long (at most {max} characters).",
    },
    "skillErr_skillMdTooLarge": {
        "zh": "SKILL.md 超过 {limit} KB。把详细的参考资料拆成单独的文件,正文里写「去读哪个文件」",
        "en": "SKILL.md is larger than {limit} KB. Move detailed reference material into separate files and point to them from the body.",
    },
    "skillErr_yamlTab": {
        "zh": "SKILL.md 第 {line} 行用 Tab 缩进了,YAML 只认空格",
        "en": "Line {line} of SKILL.md is indented with a tab; YAML only allows spaces.",
    },
    "skillErr_yamlIndent": {
        "zh": "SKILL.md 第 {line} 行的缩进对不上",
        "en": "The indentation on line {line} of SKILL.md does not line up.",
    },
    "skillErr_yamlSyntax": {
        "zh": "SKILL.md 第 {line} 行的 YAML 读不懂",
        "en": "Line {line} of SKILL.md is not valid YAML.",
    },
    "skillErr_yamlDuplicateKey": {
        "zh": "SKILL.md 第 {line} 行:{field} 写了两遍",
        "en": "Line {line} of SKILL.md: {field} appears twice.",
    },
    "skillErr_yamlUnsupported": {
        "zh": "SKILL.md 第 {line} 行用了 Mosael 不认的 YAML 写法(锚点、别名、标签之类),请写成普通的「键: 值」",
        "en": "Line {line} of SKILL.md uses YAML Mosael does not accept (anchors, aliases, tags…); please write plain “key: value”.",
    },
    "skillErr_yamlUnterminated": {
        "zh": "SKILL.md 第 {line} 行开头的引号或括号没有收尾",
        "en": "The quote or bracket opened on line {line} of SKILL.md is never closed.",
    },
    "skillErr_badPath": {
        "zh": "技能里的文件路径「{path}」不合法:要是技能文件夹里面的相对路径(不能有 ..、绝对路径或反斜杠,最多 8 层)",
        "en": "The file path “{path}” is not allowed: it must be a relative path inside the skill folder (no .., absolute paths or backslashes, at most 8 levels).",
    },
    "skillErr_noSkillMd": {
        "zh": "没找到 SKILL.md —— 一个技能是一个文件夹,里面要有一份 SKILL.md",
        "en": "No SKILL.md found; a skill is a folder containing a SKILL.md.",
    },
    "skillErr_tooManyFiles": {
        "zh": "一个技能最多 {limit} 个文件",
        "en": "A skill can have at most {limit} files.",
    },
    "skillErr_fileTooLarge": {
        "zh": "技能里的文件 {path} 超过 {limit} MB",
        "en": "The skill file {path} is larger than {limit} MB.",
    },
    "skillErr_skillTooLarge": {
        "zh": "一个技能合计不能超过 {limit} MB",
        "en": "A skill can be at most {limit} MB in total.",
    },
    "skillErr_tooManySkills": {
        "zh": "一次最多导入 {limit} 个技能",
        "en": "You can import at most {limit} skills at a time.",
    },
    "skillErr_notUtf8": {
        "zh": "{path} 不是 UTF-8 编码的文字",
        "en": "{path} is not UTF-8 text.",
    },
    "skillErr_duplicateName": {
        "zh": "这次导入里有两个技能都叫 {name}",
        "en": "Two skills in this import are both named {name}.",
    },
    "skillErr_notZip": {
        "zh": "这不是一个能打开的 .zip 文件",
        "en": "This is not a .zip file that can be opened.",
    },
    "skillErr_symlink": {
        "zh": "压缩包里有符号链接({path}),出于安全不收",
        "en": "The archive contains a symbolic link ({path}), which is refused for safety.",
    },
    "skillErr_archiveTooLarge": {
        "zh": "压缩包解开后超过 {limit} MB",
        "en": "The archive unpacks to more than {limit} MB.",
    },
    "skillErr_pluginStrayFile": {
        "zh": "插件的 skills/ 目录下只能放技能文件夹,{path} 不在任何一个技能里",
        "en": "A plugin's skills/ directory may only contain skill folders; {path} is not inside one.",
    },
}


def render(key: str, locale: str | None = None, **params: object) -> str:
    """翻一个本包的 key。查不到就原样返回 key;参数填不上就抹掉那个槽,不把 `{name}` 交给人看。"""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    want = locale or current_locale()
    text = entry.get(want) or entry.get(DEFAULT_LOCALE) or key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return "".join(literal for literal, _, _, _ in Formatter().parse(text) if literal).strip()


class FormatError(ValueError):
    """一份文件不合格式。只带 key 和参数;`str(exc)` 按**此刻**的语言说。

    是 ValueError:调用方原本按「值不对」接住它的地方不用改。
    """

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return render(self.key, None, **self.params)


def primary_tag(tag: str) -> str:
    """`zh-CN` / `zh_Hans` → `zh`。整串相等的话,一份写成 `en-US` 的翻译就白写了。"""
    return tag.replace("_", "-").split("-")[0].strip().lower()


def pick_text(value: Any, locale: str | None = None, *, author_locale: str = "") -> str:
    """一段**贴着数据写的**多语言文字:`{"zh": "…", "en": "…"}`,也可以就是一个字符串。

    这里挑的是**数据自带**的文案 —— 插件清单里作者写的、内置模板里节点的名字。那些东西没有全局
    key 可言,翻译就写在它旁边("翻译贴着它翻译的那个东西写")。

    挑哪一条:要的那种语言 → 同一主语言的任意变体(`en-US` 认 `en`)→ 作者声明的原文语言 →
    缺省语言 → 写在最前面的那一条。**退路是给原文,不是给空**。
    """
    if not isinstance(value, dict):
        return str(value or "")
    want = locale or current_locale()
    by_primary: dict[str, str] = {}
    for key, picked in value.items():
        if not isinstance(picked, str) or not picked.strip():
            continue
        by_primary.setdefault(primary_tag(str(key)), picked)
        if str(key).strip().lower() == str(want).strip().lower():
            return picked
    for candidate in (want, author_locale, DEFAULT_LOCALE):
        picked = by_primary.get(primary_tag(str(candidate))) if candidate else None
        if picked:
            return picked
    return next(iter(by_primary.values()), "")


__all__ = [
    "CURRENT_LOCALE",
    "DEFAULT_LOCALE",
    "FormatError",
    "LOCALES",
    "MESSAGES",
    "current_locale",
    "pick_text",
    "primary_tag",
    "render",
]
