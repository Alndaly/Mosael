"""一格的运行态:哪一格正在跑、客户端的快照为什么改不动服务端的运行态和产出。"""

from __future__ import annotations

from typing import Any

from app.domain.boards.producer_ids import derives_outputs
from app.domain.boards.shape import _MEDIA_KINDS


def live_job(item: dict[str, Any] | None) -> str | None:
    """这一格正在跑的任务(排队或运行中、有 job_id)。没有就是 None。"""
    run = (item or {}).get("run") or {}
    if run.get("status") in ("queued", "running") and run.get("job_id"):
        return str(run["job_id"])
    return None


def _keep_server_owned_state(stored: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """**运行态和产出归服务端,客户端的快照改不动它们。**

    画板自动保存,而生成是异步的,客户端手上那份永远可能落后于服务端刚做的事:

    · **产出已经到了**,客户端存回来的还是占位 ——
        t1 客户端存了一份带占位(run 里有 job_id、没 asset_id)的画布;
        t2 任务跑完,回执把 asset_id 填进那一项;
        t3 用户又拖了一下,客户端把**它手上那份**存回来 —— 那份里还是占位。
      产出就这么没了,而且不报错:那一项看着还在转圈,可任务早就结束了。
    · **任务还在跑**,客户端存回来的是开跑之前的样子(撤销一步就是这样)—— 任务照跑、钱照花,
      画布上却成了一个能再点一次生成的空槽,于是第二份钱也花出去了。

    所以一项在库里已经有了产出或终态,而传来的那份还是占位,保留库里那个;一项在库里正跑着
    任务,传来的那份不是这一轮,保留这一轮。别的字段(位置、表单、文字)照客户端的来。
    客户端下一次拉到的就是服务端这份。

    **只有「还在等的占位」挡得住产出**(见 _run_output_kept):传来的那份已经不在等这一轮了(撤到点生成之前、手动换了
    素材、把文档格「转为笔记」),就是人自己的编辑,照它的来 —— 画板上撤销一次运行,就是把它交回的产出从画布上拿下来,
    素材还在素材库里(ADR 0025「撤销 / 重做与 CAS」修订)。
    """
    by_id = {str(item.get("id")): item for item in ((stored or {}).get("items") or [])}
    if not by_id:
        return incoming
    items = []
    for item in incoming["items"]:
        settled = by_id.get(str(item.get("id")))
        settled_run = (settled or {}).get("run") or {}
        live = live_job(settled)
        incoming_running = (item.get("run") or {}).get("status") in ("queued", "running")
        #: 派生落点的宿主(跑着一项能力的内容格、3D 场景格)自己的字段不是这一轮的产出 —— 音频格里是
        #: 那段音频本身,归客户端。
        derived = derives_outputs(settled or item)
        if live and live_job(item) != live:
            kept = {**item, "run": settled_run}
            if not derived:
                kept.pop("asset_id", None)
            items.append(kept)
        elif settled and not derived and not item.get("asset_id") and _run_output_kept(settled, item):
            items.append({**item, "asset_id": settled["asset_id"], "run": settled.get("run", {"status": "succeeded"})})
        elif settled and incoming_running and settled_run.get("status") in ("succeeded", "failed", "cancelled"):
            # 任务结束后的下一次自动保存，客户端手里往往还是提交前的 running 快照。终态必须
            # 赢，否则它会把节点重新写活，界面就永远 loading。
            kept = {**item, "run": settled_run}
            # 便签上写字的产出是正文,没有 asset_id 可以充当「结果已到」的证据。服务端已经落下
            # 正文和清空后的表单时，晚到的 running 自动保存不能把三者一起覆盖回旧快照。
            if settled_run.get("status") == "succeeded" and settled.get("kind") == "note" and not derived:
                kept["text"] = settled.get("text", "")
                kept["form"] = settled.get("form", {})
            items.append(kept)
        else:
            items.append(item)
    return {**incoming, "items": items}


def _keep_running_cells(stored: Any, incoming: dict[str, Any], active_jobs: set[str]) -> dict[str, Any]:
    """客户端的快照里**整格都没有**的在跑的格子,任务还活着(`active_jobs`:库里还在排队 / 运行的任务)就照留。

    _keep_server_owned_state 只看传进来的那几格 —— 撤销到放下那一格之前,快照里压根没有它,存回来它就连同在跑的
    任务一起没了:任务照跑、钱照花,回执回来找不到那一格。删一格在跑的得先停(界面上「停下并删除」先取消任务,
    任务落了终态再存那份没有它的画布),所以这里只认还活着的任务。连着它的线(两头都还在的)一起留。
    界面那一侧同一条规矩在撤销时就补回去了(前端 boardServerOwned);这里兜住别的客户端、旧快照。
    """
    present = {str(item.get("id")) for item in incoming.get("items") or []}
    kept = [item for item in ((stored or {}).get("items") or [])
            if str(item.get("id")) not in present and live_job(item) in active_jobs]
    if not kept:
        return incoming
    alive = present | {str(item.get("id")) for item in kept}
    returned = {str(item.get("id")) for item in kept}
    edge_ids = {str(edge.get("id")) for edge in incoming.get("edges") or []}
    edges = [edge for edge in (stored or {}).get("edges") or []
             if str(edge.get("id")) not in edge_ids
             and (str(edge.get("source")) in returned or str(edge.get("target")) in returned)
             and str(edge.get("source")) in alive and str(edge.get("target")) in alive]
    return {**incoming, "items": [*incoming["items"], *kept], "edges": [*(incoming.get("edges") or []), *edges]}


def _run_output_kept(settled: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """库里这一格的 asset_id 是不是**一次运行交回、客户端还不知道**的产出 —— 是才替客户端补回来。

    只有一种:传来的那份还是占位(等着这一轮的产出,而库里已经收到了)—— 客户端拿着落后的快照自动保存。

    传来的那份已经不在等了,没有 asset_id 就是人拿掉的,照客户端的来:
    · 画板上撤销了那一次运行(撤到点生成之前):产出从画布上拿下来,素材还在素材库里,重做放得回来。
      此前这里把「一次运行成功落下的」也一律补回,撤销一次生成在画布上撤不掉;
    · 手动换上的素材(操作条「替换素材」把运行态写回 idle)—— 撤销它就是要回到空槽;
    · 文档格引用的文档原件 —— 它不是产出,「转为笔记」正是把它换成笔记(note_id 和 asset_id 二选一,
      补回来的话这一格从此每次保存都被 normalize 拒掉)。只有图片 / 视频 / 音频格的 asset_id 是产出。
    """
    if settled.get("kind") not in _MEDIA_KINDS or not settled.get("asset_id"):
        return False
    return ((incoming.get("run") or {}).get("status")) in ("queued", "running")
