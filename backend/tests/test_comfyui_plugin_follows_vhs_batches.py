"""VHS 分批(`VHS_BatchManager`)的工作流跑到最后一批才算完。

## 现场

视频超分要一批几十帧地跑(整段 2K 画面一次放进内存要 11 GB,5090 那台机器 31 GB 内存撑不住)。VHS 每跑完一批,
用**同一张图、同一个 client_id** 换一个新任务号重新排进队列(序号取负,插到队头);没收尾的那几批,视频合成节点在
历史里只交回 `{"unfinished_batch": [true]}`,视频在最后一批的历史里。插件此前只等提交的那一个任务号:第一批跑完
就当整个任务完成,收不到任何产出。

## 钉的是什么

- `follow_poll` 顺着同一个 client_id 一批一批跟到最后,交回带视频的那一条;
- 只认排在它后面的那几批:别的 client_id 的分批、跑过的那几批都不认。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
MODULES = tuple(path.stem for path in TOOLS.glob("*.py"))


@pytest.fixture(scope="module")
def run():
    saved = {name: sys.modules.pop(name) for name in MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import run

        yield run
    finally:
        sys.path.remove(str(TOOLS))
        for name in MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


GRAPH = {"0": {"class_type": "VHS_BatchManager", "inputs": {"frames_per_batch": 61}},
         "17": {"class_type": "VHS_VideoCombine", "inputs": {}}}
UNFINISHED = {"17": {"unfinished_batch": [True]}}
VIDEO = {"17": {"gifs": [{"filename": "mosael_sr_00001.mp4", "subfolder": "video", "type": "output"}]}}


def _entry(number: int, client_id: str, outputs: dict) -> dict:
    return {"prompt": [number, "", GRAPH, {"client_id": client_id}, ["17"]], "outputs": outputs,
            "status": {"status_str": "success", "completed": True}}


class Batches:
    """一台假的 ComfyUI:按 `script` 的顺序一批一批跑完,每问一次队列往前走一步。"""

    def __init__(self, script: list[tuple[str, int, dict]], others: dict[str, dict]) -> None:
        self.script = script
        self.finished: dict[str, dict] = dict(others)
        self.step = 0
        self.locale = "zh"

    def _advance(self) -> None:
        if self.step < len(self.script):
            task_id, number, outputs = self.script[self.step]
            self.finished[task_id] = _entry(number, "mine", outputs)
            self.step += 1

    def queue_entries(self):
        self._advance()
        if self.step < len(self.script):
            task_id, number, _ = self.script[self.step]
            return [[number, task_id, GRAPH, {"client_id": "mine"}, ["17"]]], []
        return [], []

    def queue(self):
        running, pending = self.queue_entries()
        return [item[1] for item in running], [item[1] for item in pending]

    def history(self, prompt_id: str | None = None, *, max_items: int | None = None) -> dict:
        if prompt_id:
            return {prompt_id: self.finished[prompt_id]} if prompt_id in self.finished else {}
        return dict(self.finished)


def test_顺着同一个_client_id_跟到最后一批_交回带视频的那一条(run, monkeypatch):
    monkeypatch.setattr(run, "POLL_SECONDS", 0)
    #: 别人的分批(另一个 client_id)排得更靠后,也不能被认成我的下一批。
    others = {"theirs": _entry(-30, "theirs", VIDEO)}
    comfy = Batches([("first", 15, UNFINISHED), ("second", -16, UNFINISHED), ("third", -17, UNFINISHED),
                     ("last", -18, VIDEO)], others)
    entry = run.follow_poll(comfy, "first", lambda _event: None, "zh")
    assert entry is not None and entry["outputs"] == VIDEO, "要等到最后一批,交回它的视频"
    assert entry["prompt"][0] == -18, "是我自己那串的最后一批,不是别人排在后面的那一条"


def test_不是分批的任务_跑完就交回(run, monkeypatch):
    monkeypatch.setattr(run, "POLL_SECONDS", 0)
    comfy = Batches([("only", 3, VIDEO)], {})
    entry = run.follow_poll(comfy, "only", lambda _event: None, "zh")
    assert entry is not None and entry["outputs"] == VIDEO
    assert run.unfinished_batch(entry) is False
