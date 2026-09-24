"""一轮对话在**进行中**的样子:正在流出来的文字、思考、工具调用。

前端每 1.5 秒来问一次「这一轮到哪儿了」,答案就从这里取。它是**进程内的**、只属于当前这一轮:
后端一重启,线程即死、`finally` 执行不到,会话会永远卡在「思考中」——所以启动时由
`host.reconcile_orphaned_agent_sessions()` 统一拨回(见 docs/PROCESS_STATE.md)。

从 host.py 里分出来:那边是**一轮怎么跑**(派线程、排队、计费、令牌),这边是**跑到哪儿了**。
两件事共用一个 1500 行的文件时,读的人得先分辨手里这段是哪一件。
"""

from __future__ import annotations

import threading
import time

from app.db.models import now
from app.domain.agent.textclean import decode_byte_fallback

_streams_lock = threading.Lock()


_streams: dict[str, dict] = {}


def get_stream_state(session_id: str) -> dict:
    with _streams_lock:
        state = _streams.get(session_id)
        if not state:
            return {"text": "", "done": True, "seq": 0, "timeline": []}
        snapshot = dict(state)
        snapshot["timeline"] = [dict(item) for item in state.get("timeline", [])]
        return snapshot


def _stream_reset(session_id: str) -> None:
    with _streams_lock:
        # first_token_at:这一轮**第一个** token(正文或思考,谁先算谁)到达的 monotonic 时刻。
        # 它和轮总时长一起,才把「等模型」拆成了「等第一个字」和「后面一路吐完」——只有总时长的话,
        # 一轮 30 秒既可能是模型想了 29 秒,也可能是它稳稳吐了 30 秒的长文,而这两件事该做的
        # 优化正好相反。None 表示这一轮还没吐过任何 token(或者根本没跑起来)。
        _streams[session_id] = {
            "text": "",
            "done": False,
            "seq": 0,
            "timeline": [],
            "tool_starts": {},
            "first_token_at": None,
        }


def _close_open_thinking(state: dict) -> None:
    """把最后一块还开着的思考标记为结束。

    **不能只靠 `thinking_end`**:它取决于供应商发不发那个事件,而有的(如 k3 这条链路)思考完
    直接开始吐正文,一个 end 都没有。于是那张卡顶着一个永远转不完的「思考中…」,底下正文却已经
    写完了 —— 用户看到的是矛盾的两句话。

    正文开始、或者开始调工具,本身就是思考已经结束的确凿证据,不需要供应商再宣布一次。

    只看末尾一项:任何往时间线追加的路径都会先调这个函数,所以还开着的思考块只可能在最后。

    收起时记下这段思考用了多久(`duration_seconds`),界面在「已思考」右侧显示,和工具卡一样。
    起点记在流状态里(`thinking_started`)而不是块上 —— 单调时钟的读数对前端没有意义。
    """
    timeline: list[dict] = state.setdefault("timeline", [])
    if timeline and timeline[-1].get("type") == "thinking" and not timeline[-1].get("done"):
        timeline[-1]["done"] = True
        started = state.pop("thinking_started", None)
        if started is not None:
            timeline[-1]["duration_seconds"] = round(max(0.0, time.monotonic() - started), 1)


def _stream_tool_event(session_id: str, event: dict) -> None:
    """pi 工具事件 → 流里的工具卡:tool_start 建卡(running),tool_end 更新(done/error)。

    subtool 是子智能体内部的一步,同样建卡/收卡,只是条目带 parent_id(发起它的
    run_subagent 调用)—— 界面据此嵌套在父卡下显示,轨迹里render成 SUBTOOL 行。
    """
    with _streams_lock:
        state = _streams.get(session_id)
        if state is None:
            return
        timeline: list[dict] = state.setdefault("timeline", [])
        if event.get("type") == "subagent_result":
            # 后台派发的子智能体跑完了:把存档填回发起它的那张 run_subagent 卡。
            # 卡的 content(模型看的那份「已派发」回执)不动 —— 历史不能改;details 是 UI 的。
            parent_id = str(event.get("parentCallId") or "")
            for item in timeline:
                tool = item.get("tool")
                if item.get("type") == "tool" and isinstance(tool, dict) and tool.get("id") == parent_id:
                    result = tool.get("result")
                    if not isinstance(result, dict):
                        result = {"content": result} if result is not None else {}
                    details = result.get("details")
                    if not isinstance(details, dict):
                        details = {}
                    details["subagent"] = event.get("archive")
                    result["details"] = details
                    tool["result"] = result
                    break
            state["seq"] += 1
            return
        if event.get("type") == "subtool":
            call_id = str(event.get("toolCallId") or "")
            starts = state.setdefault("tool_starts", {})
            if event.get("phase") == "start":
                starts[f"sub:{call_id}"] = time.monotonic()
                timeline.append({
                    "type": "subtool",
                    "parent_id": str(event.get("parentCallId") or ""),
                    "tool": {
                        "id": call_id,
                        "name": event.get("toolName"),
                        "args": event.get("args"),
                        "status": "running",
                        "usage": {"started_at": now().isoformat()},
                    },
                })
            else:
                started = starts.pop(f"sub:{call_id}", None)
                usage = {"finished_at": now().isoformat()}
                if isinstance(started, (int, float)):
                    usage["duration_seconds"] = round(max(0.0, time.monotonic() - started), 1)
                for item in timeline:
                    tool = item.get("tool")
                    if item.get("type") == "subtool" and isinstance(tool, dict) and tool.get("id") == call_id:
                        tool["status"] = "error" if event.get("isError") else "done"
                        tool["result"] = event.get("result")
                        tool["usage"] = {**(tool.get("usage") if isinstance(tool.get("usage"), dict) else {}), **usage}
                        break
            state["seq"] += 1
            return
        if event.get("type") == "tool_start":
            _close_open_thinking(state)
            tool_call_id = str(event.get("toolCallId") or "")
            started_at = now().isoformat()
            state.setdefault("tool_starts", {})[tool_call_id] = time.monotonic()
            card = {
                "id": tool_call_id,
                "name": event.get("name"),
                "args": event.get("args"),
                "status": "running",
                "usage": {"started_at": started_at},
            }
            timeline.append({"type": "tool", "tool": card})
        elif event.get("type") == "tool_end":
            tool_call_id = str(event.get("toolCallId") or "")
            started = state.setdefault("tool_starts", {}).pop(tool_call_id, None)
            usage = {"finished_at": now().isoformat()}
            if isinstance(started, (int, float)):
                usage["duration_seconds"] = round(max(0.0, time.monotonic() - started), 1)
            for item in timeline:
                tool = item.get("tool")
                if item.get("type") == "tool" and isinstance(tool, dict) and tool.get("id") == tool_call_id:
                    tool["status"] = "error" if event.get("isError") else "done"
                    tool["result"] = event.get("result")
                    tool["usage"] = {**(tool.get("usage") if isinstance(tool.get("usage"), dict) else {}), **usage}
                    break
        state["seq"] += 1


def _stream_thinking(session_id: str, event: dict) -> None:
    """思考增量 → 时间线上的思考块。

    **和正文分开成条**:思考不是回答,混进 text 会被落库成助手消息的内容,复制按钮也会把它
    一起复制走。单独成块还让"思考发生在哪一步之前"这件事保留下来 —— 一轮里可能思考、调工具、
    再思考,顺序本身就是信息。

    `done` 由 thinking_end 置上,前端据此把这块收起来(思考中展开、结束后折叠)。
    """
    with _streams_lock:
        state = _streams.get(session_id)
        if state is None:
            return
        timeline: list[dict] = state.setdefault("timeline", [])
        if event.get("type") == "thinking_end":
            _close_open_thinking(state)
        else:
            delta = str(event.get("delta", ""))
            if not delta:
                return
            _mark_first_token(state)
            # 未结束的那一块继续追加;已结束的不能再追加 —— 那是下一段思考。
            if timeline and timeline[-1].get("type") == "thinking" and not timeline[-1].get("done"):
                timeline[-1]["text"] = str(timeline[-1].get("text", "")) + delta
            else:
                timeline.append({"type": "thinking", "text": delta, "done": False})
                state["thinking_started"] = time.monotonic()
        state["seq"] += 1


def _mark_first_token(state: dict) -> None:
    """记下这一轮第一个 token 的时刻。**只记第一次** —— 后面的 delta 不该把它往后推。

    思考也算:对着一个「思考中…」等了八秒的人,不会因为那八秒吐的是思考就觉得自己没在等。
    """
    if state.get("first_token_at") is None:
        state["first_token_at"] = time.monotonic()


def _stream_append(session_id: str, delta: str) -> None:
    with _streams_lock:
        state = _streams.get(session_id)
        if state is not None:
            _mark_first_token(state)
            state["text"] += delta
            timeline: list[dict] = state.setdefault("timeline", [])
            # 正文开始 = 思考结束,不等供应商发 thinking_end(有的根本不发)。
            _close_open_thinking(state)
            if timeline and timeline[-1].get("type") == "text":
                timeline[-1]["text"] = str(timeline[-1].get("text", "")) + delta
            else:
                timeline.append({"type": "text", "text": delta})
            state["seq"] += 1


def _stream_finish(session_id: str, final_text: str) -> None:
    with _streams_lock:
        state = _streams.setdefault(session_id, {"text": "", "done": False, "seq": 0, "timeline": []})
        state["text"] = final_text
        timeline: list[dict] = state.setdefault("timeline", [])
        # 一轮结束时无论如何都不该再有"思考中"——哪怕这轮只思考没说话。
        _close_open_thinking(state)
        existing_text = "".join(str(item.get("text", "")) for item in timeline if item.get("type") == "text")
        if final_text and not existing_text:
            timeline.append({"type": "text", "text": final_text})
        elif final_text and final_text.startswith(existing_text) and len(final_text) > len(existing_text):
            tail = final_text[len(existing_text) :]
            if timeline and timeline[-1].get("type") == "text":
                timeline[-1]["text"] = str(timeline[-1].get("text", "")) + tail
            else:
                timeline.append({"type": "text", "text": tail})
        state["done"] = True
        state["seq"] += 1


def _timeline_for_payload(stream_state: dict, final_text: str) -> list[dict]:
    """Return the persisted, display-ready event order for one assistant turn.

    The live stream stores a denormalized text snapshot plus an ordered timeline. The snapshot
    is for quick SSE consumers; the timeline is what the chat UI needs after refresh so tool
    cards stay where they actually happened.
    """
    timeline: list[dict] = []
    for item in stream_state.get("timeline") or []:
        if item.get("type") == "text":
            text = decode_byte_fallback(str(item.get("text", "")))
            if text:
                timeline.append({"type": "text", "text": text})
        elif item.get("type") == "tool" and isinstance(item.get("tool"), dict):
            timeline.append({"type": "tool", "tool": dict(item["tool"])})
        elif item.get("type") == "subtool" and isinstance(item.get("tool"), dict):
            # 子智能体的步骤要活过刷新 —— 这里此前只认三种类型,subtool 落库时被静默丢掉,
            # 于是流式期间嵌套卡都在,一刷新全没了。
            timeline.append({"type": "subtool", "parent_id": item.get("parent_id"), "tool": dict(item["tool"])})
        elif item.get("type") == "thinking":
            text = decode_byte_fallback(str(item.get("text", "")))
            if text:
                # 落库时一律标 done:重新打开会话时那段思考早就结束了,留 False 会让它
                # 顶着一个永远转不完的"思考中"。
                block: dict = {"type": "thinking", "text": text, "done": True}
                if isinstance(item.get("duration_seconds"), (int, float)):
                    block["duration_seconds"] = item["duration_seconds"]
                timeline.append(block)
    existing_text = "".join(str(item.get("text", "")) for item in timeline if item.get("type") == "text")
    if final_text and not existing_text:
        timeline.append({"type": "text", "text": final_text})
    elif final_text and final_text.startswith(existing_text) and len(final_text) > len(existing_text):
        tail = final_text[len(existing_text) :]
        if timeline and timeline[-1].get("type") == "text":
            timeline[-1]["text"] = str(timeline[-1].get("text", "")) + tail
        else:
            timeline.append({"type": "text", "text": tail})
    return timeline
