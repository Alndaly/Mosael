"""后端文案 · 社区与资产库(ADR 0026 / 0027)。

key → {语言: 文案}。规矩见 core/i18n 与 tests/test_backend_i18n.py。
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # -- 社区(ADR 0026):账号、画板分享、发布到社区 --
    # ---- 资产库(ADR 0027):人物 / 场景 / 道具 ----
    "entityKind_character": {"zh": "人物", "en": "Character"},
    "entityKind_location": {"zh": "场景", "en": "Location"},
    "entityKind_prop": {"zh": "道具", "en": "Prop"},
    "entityRole_front": {"zh": "正面", "en": "Front"},
    "entityRole_side": {"zh": "侧面", "en": "Side"},
    "entityRole_back": {"zh": "背面", "en": "Back"},
    "entityRole_turnaround": {"zh": "三视图", "en": "Turnaround"},
    "entityRole_closeup": {"zh": "特写", "en": "Close-up"},
    "entityRole_full_body": {"zh": "全身", "en": "Full body"},
    "entityRole_expression": {"zh": "表情", "en": "Expression"},
    "entityRole_wide": {"zh": "全景", "en": "Wide shot"},
    "entityRole_reverse": {"zh": "反打", "en": "Reverse angle"},
    "entityRole_overhead": {"zh": "俯视", "en": "Overhead"},
    "entityRole_concept": {"zh": "设定图", "en": "Concept"},
    "entityRole_detail": {"zh": "细节", "en": "Detail"},
    "entityConsent_self": {"zh": "这是我本人", "en": "This is me"},
    "entityConsent_self_help": {
        "zh": "肖像是你自己的。之后用在数字人(让它说话)时,记下的是你本人的声明。",
        "en": "The likeness is your own. When it is later used for a digital human, this records your own declaration.",
    },
    "entityConsent_authorized": {"zh": "已取得本人同意", "en": "The person has given consent"},
    "entityConsent_authorized_help": {
        "zh": "肖像是别人的,你已经取得本人单独同意(《深度合成管理规定》第十四条)。没有同意不要选这一项。",
        "en": "The likeness belongs to someone else and they have given you their separate consent. Don't pick this without it.",
    },
    "entityConsent_fictional": {"zh": "虚构人物", "en": "Fictional character"},
    "entityConsent_fictional_help": {
        "zh": "不是任何真实存在的人。",
        "en": "Not any real person.",
    },
    "entityErr_notFound": {"zh": "没有这个资产", "en": "No such asset."},
    "entityErr_kind": {"zh": "资产的种类只能是 {kinds}", "en": "An asset's kind must be one of {kinds}."},
    "entityErr_nameRequired": {"zh": "资产要有一个名字", "en": "An asset needs a name."},
    "entityErr_nameTooLong": {"zh": "名字最长 {limit} 字", "en": "The name can be at most {limit} characters."},
    "entityErr_textTooLong": {"zh": "{field} 最长 {limit} 字", "en": "{field} can be at most {limit} characters."},
    "entityErr_tagsNotList": {"zh": "标签要是一串字", "en": "Tags must be a list of strings."},
    "entityErr_tooManyTags": {"zh": "一个资产最多 {limit} 个标签", "en": "An asset can have at most {limit} tags."},
    "entityErr_attributesNotObject": {"zh": "专有字段要是一个对象", "en": "The attributes must be an object."},
    "entityErr_attributeUnknown": {
        "zh": "这种资产没有这些字段:{keys};可用的是 {allowed}",
        "en": "This kind of asset has no {keys}; it has {allowed}.",
    },
    "entityErr_attributeNotText": {"zh": "{field} 要是一段字", "en": "{field} must be text."},
    "entityErr_attributeNotBool": {"zh": "{field} 要是真或假", "en": "{field} must be true or false."},
    "entityErr_attributeTooLong": {"zh": "{field} 最长 {limit} 字", "en": "{field} can be at most {limit} characters."},
    "entityErr_colorFormat": {"zh": "人偶颜色要写成 #RRGGBB", "en": "The blockout color must be written as #RRGGBB."},
    "entityErr_consentKind": {"zh": "授权声明只能是 {kinds}", "en": "The consent declaration must be one of {kinds}."},
    "entityErr_realPersonNotFictional": {
        "zh": "真人不能声明成「虚构人物」:选「这是我本人」或「已取得本人同意」",
        "en": "A real person can't be declared fictional. Pick \"This is me\" or \"The person has given consent\".",
    },
    "entityErr_fictionalConsent": {
        "zh": "虚构人物的声明只能是「虚构人物」;是真人的话先标成真人",
        "en": "A fictional character can only be declared fictional. If it's a real person, mark it as one first.",
    },
    "wfErr_entityGetNeedsTarget": {
        "zh": "「取资产」要么点名一个资产,要么给出种类和名字",
        "en": "Get from asset library needs either a picked asset or a kind and a name.",
    },
    "wfErr_entityNeedsTarget": {"zh": "先点名一个资产", "en": "Pick an asset first."},
    "wfErr_talkingModelMissing": {"zh": "选的视频模型已经不在了,换一个", "en": "The chosen video model is no longer available; pick another."},
    "wfErr_talkingResolution": {
        "zh": "分辨率「{value}」{model} 不支持,它能出 {options}",
        "en": "{model} can't output “{value}”; it offers {options}",
    },
    "wfErr_talkingNoModel": {
        "zh": "还没有会「说话照片」的视频模型 —— 在设置里接一个(如百炼 wan2.2-s2v)",
        "en": "No video model can do talking photos yet — add one in Settings (e.g. Bailian wan2.2-s2v).",
    },
    "wfErr_lipsyncNoModel": {
        "zh": "还没有会「改口型」的视频模型 —— 在设置里接一个(如百炼 videoretalk)",
        "en": "No video model can do lip sync yet — add one in Settings (e.g. Bailian videoretalk).",
    },
    "wfErr_talkingNeedsText": {"zh": "要说什么?写一段稿子,或连一张便签进来", "en": "What should it say? Write a script or connect a note."},
    "wfErr_talkingNeedsVoice": {"zh": "挑一把嗓子", "en": "Pick a voice."},
    "wfErr_talkingNeedsConsent": {
        "zh": "先确认已取得画面中人物的授权 —— 本人,或已取得其单独同意",
        "en": "Confirm you have the pictured person's consent first — it's you, or they agreed separately.",
    },
    "wfErr_talkingNeedsFace": {"zh": "没有人像", "en": "There's no portrait."},
    "wfErr_talkingNeedsVideo": {"zh": "没有要改口型的视频", "en": "There's no video to lip-sync."},
    "wfErr_entitySpeakCharacterOnly": {"zh": "「{name}」不是人物 —— 只有人物能说话", "en": "“{name}” isn't a character — only characters can talk."},
    "wfErr_entitySpeakNoConsent": {
        "zh": "「{name}」是真人,还没有「这是我本人」或「已取得本人同意」的声明 —— 在它的「设定」里补上才能说话",
        "en": "“{name}” is a real person without a “This is me” or “Consent obtained” declaration — add one in its Settings before it can talk.",
    },
    "wfErr_entitySpeakNoVoice": {
        "zh": "「{name}」还没有音色 —— 在它的「设定」里挑一把嗓子",
        "en": "“{name}” has no voice yet — pick one in its Settings.",
    },
    "wfErr_entityNeedsImage": {
        "zh": "「{name}」还没有图片参考图 —— 先传一张正面图,才画得出同一个",
        "en": "“{name}” has no reference image yet — upload a front view first so the new images can match it.",
    },
    "wfErr_entityModelMissing": {
        "zh": "选的图片模型已经不在了,换一个收参考图的模型",
        "en": "The chosen image model is no longer available; pick one that takes reference images.",
    },
    "wfErr_entityModelNoDefault": {
        "zh": "还没有默认的图片模型 —— 选一个收参考图的模型,或者在设置里设一个默认的",
        "en": "There's no default image model — pick one that takes reference images, or set a default in Settings.",
    },
    "wfErr_entityModelNoReferences": {
        "zh": "「{model}」不收参考图,只看文字画不出同一个 —— 换一个收参考图的模型",
        "en": "“{model}” doesn't take reference images, so it can't draw the same one from text alone — pick a model that does.",
    },
    "wfErr_entityAnglesScope": {"zh": "补哪些角度只能是:{options}", "en": "Which angles must be one of: {options}"},
    "wfErr_entityAnglesComplete": {
        "zh": "「{name}」要补的角度都有了;要重画的话选「每个角度都重画」",
        "en": "“{name}” already has every angle; choose “Redraw every angle” to draw them again.",
    },
    "wfErr_entityExpressionsCharacterOnly": {
        "zh": "「{name}」不是人物 —— 只有人物能生成表情",
        "en": "“{name}” isn't a character — only characters have expressions.",
    },
    "wfErr_entityNothingDrawn": {"zh": "一张都没画出来", "en": "No image was drawn."},
    "wfErr_entitySaveNeedsName": {"zh": "「存成资产」要一个名字", "en": "Save to asset library needs a name."},
    "wfErr_entitySaveIfExists": {"zh": "同名时怎么办只能是:{options}", "en": "When one exists, choose one of: {options}"},
    "entityErr_voiceEngineUnknown": {
        "zh": "不认识的配音引擎:{engine}",
        "en": "Unknown voice engine: {engine}",
    },
    "entityErr_attributeTargetGone": {
        "zh": "{field} 指的东西不在这个工作区里",
        "en": "What {field} points at isn't in this workspace.",
    },
    "entityErr_variantOfVariant": {"zh": "变体下面不能再建变体", "en": "A variant can't have variants of its own."},
    "entityErr_variantKind": {"zh": "变体和母体是同一种资产", "en": "A variant is the same kind of asset as its parent."},
    "entityErr_coverNotAReference": {"zh": "封面要是这个资产自己的一张参考图", "en": "The cover must be one of this asset's own reference images."},
    "entityErr_coverNotImage": {"zh": "封面要是一张图片", "en": "The cover must be an image."},
    "entityErr_hasVariants": {
        "zh": "这个资产下面有 {count} 个变体,要连它们一起删",
        "en": "This asset has {count} variant(s); delete them along with it.",
    },
    "entityErr_role_character": {
        "zh": "人物的参考图只能标成正面、侧面、背面、三视图、特写、全身、表情、设定图或细节",
        "en": "A character's reference can be front, side, back, turnaround, close-up, full body, expression, concept or detail.",
    },
    "entityErr_role_location": {
        "zh": "场景的参考图只能标成全景、反打、俯视、设定图或细节 —— 场景没有正面、侧面",
        "en": "A location's reference can be a wide shot, reverse angle, overhead, concept or detail — locations have no front or side.",
    },
    "entityErr_role_prop": {
        "zh": "道具的参考图只能标成正面、侧面、背面、三视图、特写、设定图或细节",
        "en": "A prop's reference can be front, side, back, turnaround, close-up, concept or detail.",
    },
    "entityErr_assetNotInWorkspace": {"zh": "这份素材不在这个工作区的素材库里", "en": "That media isn't in this workspace's library."},
    "entityErr_referenceKind": {"zh": "参考图要是图片或视频", "en": "A reference must be an image or a video."},
    "entityErr_tooManyReferences": {
        "zh": "一个资产最多挂 {limit} 张参考图;更多的角度可以拆成变体",
        "en": "An asset can hold at most {limit} references; split further looks into variants.",
    },
    "entityErr_referenceNotFound": {"zh": "这张图不是这个资产的参考图", "en": "That image isn't one of this asset's references."},
    "entityErr_reorderMismatch": {
        "zh": "参考图刚刚有人改过,刷新之后再排一次",
        "en": "The references just changed. Refresh and reorder again.",
    },
    "entityErr_tooManyMentions": {"zh": "一次最多点名 {limit} 个资产", "en": "At most {limit} assets can be mentioned at once."},
    "entityErr_mentionGone": {
        "zh": "点名的资产 {id} 不在这个工作区里(可能已经删了)",
        "en": "The mentioned asset {id} isn't in this workspace (it may have been deleted).",
    },
    "genErr_tooManySubjects": {
        "zh": "{provider}/{model} 一次最多引用 {cap} 个主体,这次给了 {count} 组参考图",
        "en": "{provider}/{model} can reference at most {cap} subjects at once; this request has {count} groups of references.",
    },
    "boardErr_entityNeedsId": {"zh": "资产格需要 entity_id", "en": "An asset item needs an entity_id."},
    "boardErr_entityNotInWorkspace": {"zh": "资产格引用的资产不在这个工作区里", "en": "The asset that item points at isn't in this workspace."},
}
