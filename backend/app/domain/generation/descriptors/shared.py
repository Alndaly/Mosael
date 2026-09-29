"""素材角色的名字与说明、两组互斥素材、共用的张数上限 —— 好几家描述符都要用的那几块。

由 domain/generation/catalog 统一重新导出;调用方照旧从 catalog 取,这里只放数据。
"""

from __future__ import annotations

#: 一份素材**能给几份**,按角色分开算。描述符里写 `source_limits`,校验在
#: domain/generation/operations.validate_against_capabilities 里统一做。
#:
#: 这些数字全部来自接口自己的报错(见 tests/test_capabilities_match_reality.py 里的原话),
#: 不是从文档抄的「建议值」—— 此前一个都没写,于是界面上想挂几张挂几张,超了就是一个
#: 提交期 400,而错误信息是英文的、说的是 `content` 数组下标。
#:
#: **首尾帧组和参考素材组互斥**,写在 `exclusive_source_groups` 里:同一次生成只能用其中
#: 一组。这不是我们加的规矩,是火山原话 `first/last frame content cannot be mixed with
#: reference media content`;可灵那边的说法是「不支持仅尾帧图生视频」,所以尾帧还额外
#: 依赖首帧(见各家描述符里的 `requires_source`)。
#: 每种素材角色**叫什么、是干什么的**。一份,三个消费者:提交前的校验拿它写报错、
#: 智能体拿它知道每个参数该给什么、界面拿它做标题。
#:
#: 此前这张表存在三份(operations 的中文名、mcp_server 的说明、前端的 ROLE_COPY),而
#: 新增角色时漏掉哪一份都不会报错 —— 只是智能体不知道有这个东西,于是永远不会用它。
#: 事实上到这次为止,mcp_server 那份就漏了参考音频、待编辑的视频、待续写的片段、驱动音频四种。
SOURCE_ROLE_LABELS = {
    "first_frame": "首帧",
    "last_frame": "尾帧",
    "reference_image": "参考图",
    "reference_video": "参考视频",
    "reference_audio": "参考音频",
    "source_video": "待编辑的视频",
    "first_clip": "待续写的片段",
    "driving_audio": "驱动音频",
    "mask": "蒙版",
}

#: 给智能体的一句话:这个角色到底是什么意思。**光有名字不够** —— 「参考视频」和「待编辑的
#: 视频」都是视频,分不清的话它会拿编辑模型去做参考生成,而画面出得来、只是不是那一段。
SOURCE_ROLE_HELP = {
    "first_frame": "成片的第一格画面;asset_id 或 first_frame_url 外链",
    "last_frame": "成片的最后一格;有的模型要求它和首帧一起给(看各模型自己的规矩),有的可以单独给",
    "reference_image": "照着它的风格和主体来拍;它自己一帧都不出现在成片里",
    "reference_video": "照着它的风格和主体来拍;成片是新的,不是它",
    "reference_audio": "参考音色/风格,不驱动画面;生成音乐时是「照这首的风格来」",
    "source_video": "**被处理的那一段视频**;视频编辑时成片是它改过之后的样子,生成音频时产出的声音按它的画面对齐",
    "first_clip": "**被接着往下拍/往下写的那一段**;成片以它开头,总时长要比它长(音频续写时是一段音频)",
    "driving_audio": "画面跟着它走 —— 口型同步、动作卡点",
    "mask": "局部重绘的蒙版:白色是要改的地方,和要改的那张图(参考图)一起给",
}

KEYFRAME_GROUP = ["first_frame", "last_frame"]

REFERENCE_GROUP = ["reference_image", "reference_video", "reference_audio"]

#: 「这一次用哪一组素材」。上面两组在 Seedance 这类模型上**互斥**(火山原话见下方
#: exclusive_source_groups)。整片流程里每一镜走哪条路是逐镜决定的:两组素材都接上,再由这一项
#: 选一组 —— 比为两条路各画一个生成节点、再在下游合流干净。选了一组就丢掉与它互斥的那一组,
#: 两组之外的角色(待编辑的视频、驱动音频……)不受影响。
SOURCE_GROUPS = ("all", "keyframes", "references")

SOURCE_GROUP_DROPS = {"keyframes": tuple(REFERENCE_GROUP), "references": tuple(KEYFRAME_GROUP)}

#: 火山 Seedance 2 与 MiniMax H3 给的数字**一模一样**(9 / 3 / 3),两家的报错措辞不同但
#: 结论相同,所以这里合成一份共用常量,而不是抄两遍。
REFERENCE_SCENE_LIMITS = {"reference_image": 9, "reference_video": 3, "reference_audio": 3}
