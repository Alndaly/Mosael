"""每种任务**在界面上**是什么:叫什么、做完要不要说、改动了哪些东西、在哪一页看它的记录。

任务总线(jobs.py)不认识任何具体领域;这张表是给总线之外的消费者看的 —— 任务中心、任务详情、
工作流运行历史。此前这些信息是前端的四张手写表,彼此对不上(配音合成在一处叫「配音合成」,
在另一处叫「任务」),还列着一个后端从不创建的种类。见 ADR-0018。

加一个任务种类 = 在 JOB_KINDS 里加一行,再在前端给它一个图标;漏了哪一样都有测试会红。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: 做完之后要不要告诉用户。always:弹提示、发系统通知;failures:只有失败才说
#: (没人主动要的维护活,比如预览代理);never:只在任务中心里看得到。
#: 只对**顶层**任务生效 —— 子任务由它的父任务替它说。
Announce = Literal["always", "failures", "never"]

#: 任务做完后可能变了的东西。前端把每一种映射到自己的缓存键,后端不知道 React Query。
Resource = Literal["assets", "sequences", "transcripts", "workflows", "publish_tasks", "generations", "boards", "entities"]


@dataclass(frozen=True)
class JobKind:
    kind: str
    announce: Announce
    affects: tuple[Resource, ...]
    #: 在哪一页看这条任务的结果(前端的页面 id);None 表示没有专门的页面。
    view: str | None = None
    #: payload 里哪个字段是那一页上**那条记录**的 id。
    record_field: str | None = None

    @property
    def label_key(self) -> str:
        return f"jobKind_{self.kind}"


JOB_KINDS: dict[str, JobKind] = {
    entry.kind: entry
    for entry in (
        JobKind("workflow", "always", ("assets", "sequences", "workflows"), view="workflows", record_field="workflow_id"),
        JobKind("publish", "always", ("publish_tasks",), view="publish", record_field="task_id"),
        JobKind("render", "always", ("assets", "sequences"), view="editor"),
        JobKind("transcribe", "always", ("assets", "transcripts"), view="editor"),
        JobKind("subtitle_dub", "always", ("assets", "sequences"), view="editor"),
        JobKind("ai_generation", "always", ("assets", "generations"), view="ai"),
        JobKind("tts", "always", ("assets",), view="ai"),
        JobKind("podcast", "always", ("assets",), view="ai"),
        JobKind("url_import", "always", ("assets",), view="media"),
        JobKind("video_to_gif", "always", ("assets",), view="media"),
        JobKind("denoise_audio", "always", ("assets",), view="media"),
        JobKind("separate_audio", "always", ("assets",), view="media"),
        # 剪辑台上对片段做声音处理:产出进素材库,并直接换到时间线上(voices/clip_audio)。
        JobKind("clip_audio", "always", ("assets", "sequences"), view="editor"),
        # 文档解析(ADR 0031):导入时自动跑本地解析,是没人主动要的维护活 —— 只有失败才说;结果在素材详情里看。
        JobKind("document_parse", "failures", ("assets",), view="media"),
        JobKind("trim", "always", ("assets", "boards"), view="boards"),
        # 画板上写字:结果落在那张便签(文档格)上,在跑时格子上转圈、能停,失败写在格子上 —— 不另弹通知。
        JobKind("board_write", "never", ("boards",), view="boards"),
        # 画板上一格的能力跑一个节点(插件工具、转写、分离……):可能要几分钟,用户多半已经去干别的了。
        # 产出落成画板上的新格子,插件交出的文件还会进素材库。
        #: 资产格的能力(补全多角度、生成表情)还会把画成的图挂回资产。
        JobKind("board_run", "always", ("boards", "assets", "entities"), view="boards"),
        # 资产详情页上的「补全多角度」「生成表情」:几张图一起画,要一两分钟;画成的挂回那个资产。
        JobKind("entity_draw", "always", ("entities", "assets", "generations"), view="entities",
                record_field="entity_id"),
        # 导入、导出之后顺手排的;成功了没人在等,失败了才值得一说(素材预览会不流畅)。
        JobKind("proxy", "failures", ("assets",), view="media"),
    )
}

#: 目录里没有的种类(外部 worker 自定义的、老数据里的)按这一条显示。
FALLBACK = JobKind("", "always", ("assets",))
FALLBACK_LABEL_KEY = "jobKind_other"


def job_kind(kind: str) -> JobKind:
    return JOB_KINDS.get(kind, FALLBACK)
