"""镜头表的五张封闭词表。词和判据照 reelbench-skills video-shots 的 taxonomy(Apache-2.0)。

**封闭**是这张表有用的前提:每人一套说法的表汇总不出任何东西(「中近景」「胸部以上」「MCU」是同一个景别)。
模型写了表外的词,对账时清空并记一条提示,不猜它想说哪个。

**不和故事板那套共用**(workflows/templates_schemas 的 SHOT_SIZES / CAMERA_MOVES):那是「要怎么拍」交给生成模型的词,
这是「拍成了什么」拿来统计的词;两边各自演进,耦在一起改一边坏一边。
"""

from __future__ import annotations

SIZES: dict[str, dict[str, str]] = {
    "none": {"zh": "无景别", "en": "No framing"},
    "extreme-wide": {"zh": "大远景", "en": "Extreme wide"},
    "wide": {"zh": "全景", "en": "Wide"},
    "medium-wide": {"zh": "中远景", "en": "Medium wide"},
    "medium": {"zh": "中景", "en": "Medium"},
    "medium-close": {"zh": "中近景", "en": "Medium close-up"},
    "close": {"zh": "特写", "en": "Close-up"},
    "extreme-close": {"zh": "大特写", "en": "Extreme close-up"},
}

CATEGORIES: dict[str, dict[str, str]] = {
    "establishing": {"zh": "定场", "en": "Establishing"},
    "subject": {"zh": "主体", "en": "Subject"},
    "dialogue": {"zh": "对话", "en": "Dialogue"},
    "reaction": {"zh": "反应", "en": "Reaction"},
    "insert": {"zh": "插入特写", "en": "Insert"},
    "pov": {"zh": "主观", "en": "POV"},
    "empty": {"zh": "空镜", "en": "Empty"},
    "product": {"zh": "产品展示", "en": "Product"},
    "text-card": {"zh": "字卡", "en": "Text card"},
    "transition": {"zh": "转场镜头", "en": "Transition"},
    "archive": {"zh": "引用素材", "en": "Archive"},
}

#: 运镜 → (名字, 实测档)。实测档是这个词在像素上必然留下的痕迹:strong = 整幅画面必然在动;
#: still = 机位不动(人在画里跑照样是固定);subtle = 变化太小或太局部,测不出来、不查。
CAMERA_MOVES: dict[str, tuple[dict[str, str], str]] = {
    "static": ({"zh": "固定", "en": "Static"}, "still"),
    "push-in": ({"zh": "推", "en": "Push in"}, "strong"),
    "pull-out": ({"zh": "拉", "en": "Pull out"}, "strong"),
    "zoom-in": ({"zh": "变焦推", "en": "Zoom in"}, "strong"),
    "zoom-out": ({"zh": "变焦拉", "en": "Zoom out"}, "strong"),
    "pan-left": ({"zh": "左摇", "en": "Pan left"}, "strong"),
    "pan-right": ({"zh": "右摇", "en": "Pan right"}, "strong"),
    "tilt-up": ({"zh": "上摇", "en": "Tilt up"}, "strong"),
    "tilt-down": ({"zh": "下摇", "en": "Tilt down"}, "strong"),
    "truck-left": ({"zh": "左移", "en": "Truck left"}, "strong"),
    "truck-right": ({"zh": "右移", "en": "Truck right"}, "strong"),
    "pedestal-up": ({"zh": "升", "en": "Pedestal up"}, "strong"),
    "pedestal-down": ({"zh": "降", "en": "Pedestal down"}, "strong"),
    "tracking": ({"zh": "跟拍", "en": "Tracking"}, "strong"),
    "arc": ({"zh": "环绕", "en": "Arc"}, "strong"),
    "whip-pan": ({"zh": "甩镜", "en": "Whip pan"}, "strong"),
    "handheld": ({"zh": "手持微晃", "en": "Handheld"}, "subtle"),
    "shake": ({"zh": "剧烈晃动", "en": "Shake"}, "strong"),
    "rack-focus": ({"zh": "变焦点", "en": "Rack focus"}, "subtle"),
    "micro-push": ({"zh": "微推", "en": "Micro push"}, "subtle"),
    "roll": ({"zh": "旋转", "en": "Roll"}, "strong"),
    "drone": ({"zh": "航拍移动", "en": "Drone"}, "strong"),
}

TRANSITIONS: dict[str, dict[str, str]] = {
    "cut": {"zh": "硬切", "en": "Cut"},
    "dissolve": {"zh": "叠化", "en": "Dissolve"},
    "fade-in": {"zh": "淡入", "en": "Fade in"},
    "fade-out": {"zh": "淡出", "en": "Fade out"},
    "whip": {"zh": "甩切", "en": "Whip"},
    "match-cut": {"zh": "匹配剪辑", "en": "Match cut"},
    "wipe": {"zh": "划像", "en": "Wipe"},
    "morph": {"zh": "特效转场", "en": "Morph"},
}

#: 节奏角色:观众这一刻得到了什么(为什么还没划走)。
RHYTHMS: dict[str, dict[str, str]] = {
    "hook": {"zh": "钩子", "en": "Hook"},
    "setup": {"zh": "铺垫", "en": "Setup"},
    "build": {"zh": "递进", "en": "Build"},
    "beat": {"zh": "重音", "en": "Beat"},
    "turn": {"zh": "转折", "en": "Turn"},
    "payoff": {"zh": "兑现", "en": "Payoff"},
    "breath": {"zh": "换气", "en": "Breath"},
    "close": {"zh": "收口", "en": "Close"},
}

#: 画面描述里不许出现的空话:写了等于没写,而且读起来像判断过了。
EMPTY_WORDS = ("氛围感", "高级感", "视觉冲击", "令人", "唯美", "美不胜收", "大气磅礴", "震撼人心", "画面感十足", "很美",
               "非常美", "精美绝伦", "赏心悦目", "引人入胜", "stunning", "breathtaking", "cinematic feel", "visually striking")

#: 运镜门的两条线(帧间差,0–255):声称 strong 而实测低于前者 —— 判错了;声称固定而实测高于后者 —— 只提示。
STRONG_MIN_MOTION = 1.5
STILL_MAX_MOTION = 12.0
#: 不到这么长的镜头不查运镜:掐掉两头之后剩不下几个采样。
GATE_MIN_SECONDS = 1.0


def camera_class(move: str) -> str:
    return CAMERA_MOVES[move][1] if move in CAMERA_MOVES else ""


def label(table: dict[str, dict[str, str]], value: str, lang: str) -> str:
    names = table.get(value)
    return names.get("en" if lang == "en" else "zh", value) if names else value


def camera_label(move: str, lang: str) -> str:
    entry = CAMERA_MOVES.get(move)
    return entry[0].get("en" if lang == "en" else "zh", move) if entry else move
