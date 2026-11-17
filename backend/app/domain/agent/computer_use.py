"""Computer Use 的宿主桥:L1 操作 Mosael 自己,L3 观察/操作其他桌面应用(ADR 0075 / 0081)。

L1 图由 Electron 用 `webContents.capturePage()` 拍 Mosael 自己的渲染,不需要屏幕录制权限;
L3 由 DesktopDriverMac 枚举其他应用窗口、截图、读取 AX 树,并在一次性令牌/截图绑定后执行点击、输入和按键。

线程模型和进程边界:

    工具(mcp_server) ── 这里 ──127.0.0.1 回环桥──→ Electron 主进程 ── DesktopDriver

Electron 的 `ipcMain` 只服务渲染层,后端(Python,另一个进程)够不着它。主进程在启动时开一条
只绑回环、带每进程随机令牌、通道写死的一问一答桥。壳拉起的后端拿
`MOSAEL_HOST_BRIDGE_PORT` / `MOSAEL_HOST_BRIDGE_TOKEN`;`pnpm dev:backend` 单独起的
后端读同一个数据目录里的 `host-bridge.json`(0600)。远程团队服务器没有这条桥,工具会回一句人话。

缩放放在后端:Electron 只负责拍回原图,这里按 `scale` 缩小再交给模型。
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import socket
from typing import Any
from app.core.config import settings

#: 电脑使用**只有一个窗口**:应用主窗口。曾经还有 `publish`(发布器自己的 BrowserWindow),
#: 但发布器后来成了应用里的页面与内嵌浏览器 —— 那个名字早就没有对应的窗口了(ADR 0075)。
#: 所以这里不再有"选哪个窗口"这一维:少一维就少一个永远走不通的分支。

#: 缩放范围:0.25 足够看清布局,1 是原样。别让模型把图缩成 1 像素。
MIN_SCALE = 0.25
MAX_SCALE = 1.0
DEFAULT_SCALE = 1.0

#: 桥的一次请求。回环上只有本机进程,给足拍一张图的时间,但不挂死。
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 30.0
#: 一条消息的上限(20 MB):5K 窗口的 PNG 也在里面,再大就是对面出了问题。
MAX_MESSAGE_BYTES = 20 * 1024 * 1024

BRIDGE_PORT_ENV = "MOSAEL_HOST_BRIDGE_PORT"
BRIDGE_TOKEN_ENV = "MOSAEL_HOST_BRIDGE_TOKEN"
#: 壳写在数据目录里的桥地址(0600)。和 main.cjs 的 HOST_BRIDGE_FILE 是同一个文件名。
BRIDGE_FILE = "host-bridge.json"
#: 桥上的通道名。和 `electron/ipc-contract.cjs` 的 `IPC.invoke.computerScreenshot` 等是同一批字符串。
SCREENSHOT_CHANNEL = "computer:screenshot"
DESKTOP_WINDOWS_CHANNEL = "computer:desktop-windows"
DESKTOP_SCREENSHOT_CHANNEL = "computer:desktop-screenshot"
DESKTOP_FULL_SCREENSHOT_CHANNEL = "computer:desktop-full-screenshot"
DESKTOP_ACCESSIBILITY_CHANNEL = "computer:desktop-accessibility"
DESKTOP_CLICK_CHANNEL = "computer:desktop-click"
DESKTOP_POINTER_CHANNEL = "computer:desktop-pointer"
DESKTOP_TYPE_CHANNEL = "computer:desktop-type"
DESKTOP_SCROLL_CHANNEL = "computer:desktop-scroll"
#: 动手:L1 的点击与输入(ADR 0075 的 P1)。坐标是**看着的那张图**上的(缩放过的)像素,
#: 这里除以 scale 换成窗口的 CSS 像素再交给主进程 —— 模型不需要知道缩放这回事。
CLICK_CHANNEL = "computer:click"
POINTER_CHANNEL = "computer:pointer"
DRAG_CHANNEL = "computer:drag"
TYPE_CHANNEL = "computer:type"
KEY_CHANNEL = "computer:key"
SCROLL_CHANNEL = "computer:scroll"
DESKTOP_KEY_CHANNEL = "computer:desktop-key"
DESKTOP_DRAG_CHANNEL = "computer:desktop-drag"
WAIT_CHANNEL = "computer:wait"
DESKTOP_WAIT_CHANNEL = "computer:desktop-wait"
VERIFY_CHANNEL = "computer:verify"
DESKTOP_VERIFY_CHANNEL = "computer:desktop-verify"
OCR_CHANNEL = "computer:ocr"
DESKTOP_OCR_CHANNEL = "computer:desktop-ocr"
CLIPBOARD_READ_CHANNEL = "computer:clipboard-read"
CLIPBOARD_WRITE_CHANNEL = "computer:clipboard-write"
#: 这一轮结束了 —— 让主进程把「被控制中」熄灭(不是急停:下一轮还能动)。
END_CHANNEL = "computer:end"
#: 一次滚动最多几格滚轮。再多就不是「往下看看」,而是整段跳走。
MAX_SCROLL_NOTCHES = 30
#: 拖拽按真实时间走:太快页面收不到中间移动,太慢像卡住。100ms–2s 足够覆盖框选与拖文件。
MIN_DRAG_MS = 100
MAX_DRAG_MS = 2000
DEFAULT_DRAG_MS = 300
#: 等一段界面文字出现。太短来不及重渲染,太长会把一次失败拖成半分钟。
MIN_WAIT_MS = 100
MAX_WAIT_MS = 15_000
DEFAULT_WAIT_MS = 5_000

#: 能点的键。L3 仍然只开放左右键;L1 额外支持中键,但它与 L3 的驱动能力不是一回事。
CLICK_BUTTONS = ("left", "right", "middle")
L1_BUTTONS = ("left", "right", "middle")
L1_POINTER_ACTIONS = ("hover", "down", "up")
MAX_HOLD_MS = 300_000
#: 一次最多输入这么多字符。再多就不是「在输入框里写一句话」,而是整段粘贴了。
MAX_TYPE_CHARS = 2000

#: 按键与修饰键:和真正的键盘事件同一套名字。文本输入不走这里(见 `type_text`)。
KEY_MODIFIERS = frozenset({"cmd", "ctrl", "alt", "shift", "meta"})
SPECIAL_KEYS = frozenset({
    "enter", "tab", "escape", "backspace", "delete", "space",
    "home", "end", "pageup", "pagedown", "left", "right", "up", "down",
    "arrowleft", "arrowright", "arrowup", "arrowdown", "return", "esc",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
})

#: 这些应用即使只读截图也不把像素交出去(与 Electron 驱动的动作黑名单对齐)。
PROTECTED_OWNERS = frozenset({
    "1Password", "1Password 7", "Bitwarden", "Dashlane", "Keeper", "KeePassXC",
    "Keychain Access", "钥匙串访问", "Passwords", "密码", "SecurityAgent",
    "System Settings", "System Preferences", "系统设置", "系统偏好设置",
    "Terminal", "终端", "iTerm2", "Warp", "loginwindow",
})


class ComputerUseError(ValueError):
    """给模型看的一句话。不是 traceback,也不是 HTTP 500 —— 模型据此改参数或告诉用户。"""


def clipboard_read() -> dict[str, Any]:
    """读取系统剪贴板文本。敏感操作;确认与管理员门在确认工具层。"""
    answer = _host_call(CLIPBOARD_READ_CHANNEL, {})
    if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
        raise ComputerUseError("The clipboard bridge answered without text.")
    return {"text": answer["text"], "length": len(answer["text"])}


def clipboard_write(text: object) -> dict[str, Any]:
    """写入系统剪贴板文本。敏感操作;确认与管理员门在确认工具层。"""
    if not isinstance(text, str):
        raise ComputerUseError("text must be a string.")
    if len(text) > 100_000:
        raise ComputerUseError("text must be at most 100000 characters.")
    answer = _host_call(CLIPBOARD_WRITE_CHANNEL, {"text": text})
    if not isinstance(answer, dict) or answer.get("written") != len(text):
        raise ComputerUseError("The clipboard bridge answered without confirming the write.")
    return {"written": len(text)}


def screenshot(scale: float = DEFAULT_SCALE) -> dict[str, Any]:
    """拍一张 Mosael 主窗口,返回 `{width, height, scale, image}`(`image` 是 PNG 的 base64)。

    参数不对时抛 `ComputerUseError`(一句人话),不会走到 Electron。
    """
    factor = _scale(scale)

    answer = _host_call(SCREENSHOT_CHANNEL, {})
    if not isinstance(answer, dict):
        raise ComputerUseError("computer_screenshot got no answer from the Mosael window bridge.")

    raw = _image_bytes(answer)
    width, height, raw = _size_and_pixels(raw, factor)
    elements = _scaled_elements(answer.get("elements"), factor)
    return {
        "width": width,
        "height": height,
        "scale": factor,
        **({"elements": elements} if elements else {}),
        "image": base64.b64encode(raw).decode("ascii"),
    }


def zoom(region: object, scale: float = DEFAULT_SCALE) -> dict[str, Any]:
    """按全屏像素裁出 Mosael 窗口的一块区域,再按 `scale` 缩小;用于读小字和密集 UI。"""
    box = _region(region)
    factor = _scale(scale)
    answer = _host_call(SCREENSHOT_CHANNEL, {})
    if not isinstance(answer, dict):
        raise ComputerUseError("computer_zoom got no answer from the Mosael window bridge.")
    raw = _image_bytes(answer)
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG":
                raise ComputerUseError("The Mosael window returned something that isn't a PNG.")
            source_width, source_height = image.size
            x0, y0, x1, y1 = box
            if x1 > source_width or y1 > source_height:
                raise ComputerUseError(
                    f"region is outside the screenshot: it is {source_width}×{source_height}, "
                    f"but region ends at ({x1}, {y1})."
                )
            cropped = image.crop(box)
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
    except ComputerUseError:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise ComputerUseError("The Mosael window returned something that isn't a readable PNG.") from None
    width, height, pixels = _size_and_pixels(buffer.getvalue(), factor)
    return {
        "width": width,
        "height": height,
        "scale": factor,
        "source_width": source_width,
        "source_height": source_height,
        "region": list(box),
        "image": base64.b64encode(pixels).decode("ascii"),
    }


def wait(text: object, timeout_ms: object = DEFAULT_WAIT_MS) -> dict[str, Any]:
    """等 Mosael 窗口里出现一段可见文字;找到返回 found=True,等满返回 False。只读。"""
    label = _wait_text(text)
    timeout = _wait_timeout(timeout_ms)
    answer = _host_call(WAIT_CHANNEL, {"text": label, "timeoutMs": timeout})
    if not isinstance(answer, dict) or not isinstance(answer.get("found"), bool):
        raise ComputerUseError("The Mosael window bridge answered without a wait result.")
    return {**answer, "text": label, "timeoutMs": timeout}


def verify(text: object, absent: object = False) -> dict[str, Any]:
    """立即检查 Mosael 窗口里有没有一段可见文字;不等待,只给一个可判定的结果。"""
    label = _wait_text(text)
    missing = _bool_flag(absent, "absent")
    answer = _host_call(VERIFY_CHANNEL, {"text": label, "absent": missing})
    if not isinstance(answer, dict) or not isinstance(answer.get("ok"), bool):
        raise ComputerUseError("The Mosael window bridge answered without a verification result.")
    return {**answer, "text": label, "absent": missing}


def desktop_verify(pid: object, text: object, absent: object = False) -> dict[str, Any]:
    """立即检查一个桌面应用的 AX 树里有没有一段文字;只读。"""
    target = _desktop_id(pid, "pid")
    label = _wait_text(text)
    missing = _bool_flag(absent, "absent")
    answer = _host_call(DESKTOP_VERIFY_CHANNEL, {"pid": target, "text": label, "absent": missing})
    if not isinstance(answer, dict) or not isinstance(answer.get("ok"), bool):
        raise ComputerUseError("The desktop bridge answered without a verification result.")
    return {**answer, "pid": target, "text": label, "absent": missing}


def desktop_wait(pid: object, text: object, timeout_ms: object = DEFAULT_WAIT_MS) -> dict[str, Any]:
    """等一个桌面应用的 AX 树里出现一段文字;只读,不注入输入。"""
    target = _desktop_id(pid, "pid")
    label = _wait_text(text)
    timeout = _wait_timeout(timeout_ms)
    answer = _host_call(DESKTOP_WAIT_CHANNEL, {"pid": target, "text": label, "timeoutMs": timeout})
    if not isinstance(answer, dict) or not isinstance(answer.get("found"), bool):
        raise ComputerUseError("The desktop bridge answered without a wait result.")
    return {**answer, "pid": target, "text": label, "timeoutMs": timeout}


def ocr() -> dict[str, Any]:
    """对 Mosael 主窗口做本地 OCR(macOS Vision);只读。"""
    answer = _host_call(OCR_CHANNEL, {})
    if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
        raise ComputerUseError("The OCR bridge answered without text.")
    return {"text": answer["text"], "lines": answer.get("lines") or []}


def desktop_ocr(window_id: object) -> dict[str, Any]:
    """对一个桌面窗口做本地 OCR;窗口受保护时驱动会拒绝。只读。"""
    target = _desktop_id(window_id, "window_id")
    answer = _host_call(DESKTOP_OCR_CHANNEL, {"windowNumber": target})
    if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
        raise ComputerUseError("The desktop OCR bridge answered without text.")
    return {"window_id": target, "text": answer["text"], "lines": answer.get("lines") or []}


def desktop_full_screenshot(scale: float = DEFAULT_SCALE) -> dict[str, Any]:
    """拍整个桌面;受保护应用在屏时 Electron 驱动会拒绝。只读。"""
    factor = _scale(scale)
    answer = _host_call(DESKTOP_FULL_SCREENSHOT_CHANNEL, {})
    raw = _image_bytes(answer)
    width, height, raw = _size_and_pixels(raw, factor)
    return {
        "width": width,
        "height": height,
        "scale": factor,
        "image": base64.b64encode(raw).decode("ascii"),
    }


def desktop_windows() -> dict[str, Any]:
    """列出当前可见的桌面窗口;id 用于截图,pid 用于 AX 树。"""
    answer = _host_call(DESKTOP_WINDOWS_CHANNEL, {})
    windows = answer.get("windows")
    if not isinstance(windows, list) or not all(isinstance(window, dict) for window in windows):
        raise ComputerUseError("The desktop window bridge answered without a valid window list.")
    return {"windows": windows}


def desktop_screenshot(window_id: object, scale: float = DEFAULT_SCALE) -> dict[str, Any]:
    """截一张其他应用的可见窗口;只读,不注入任何输入。"""
    target = _desktop_id(window_id, "window_id")
    factor = _scale(scale)
    answer = _host_call(DESKTOP_SCREENSHOT_CHANNEL, {"windowNumber": target})
    raw = _image_bytes(answer)
    width, height, raw = _size_and_pixels(raw, factor)
    meta = answer.get("meta")
    owner = str(meta.get("owner") or "") if isinstance(meta, dict) else ""
    capture_id = str(meta.get("capture_id") or "") if isinstance(meta, dict) else ""
    if not capture_id:
        raise ComputerUseError("The desktop window bridge answered without a capture binding.")
    protected = owner in PROTECTED_OWNERS
    if protected:
        raw = _protected_placeholder(width, height)
    return {
        "window_id": target,
        "capture_id": capture_id,
        "width": width,
        "height": height,
        "scale": factor,
        "image": base64.b64encode(raw).decode("ascii"),
        **({"protected": True, "owner": owner} if protected else {}),
    }


def desktop_accessibility(pid: object) -> dict[str, Any]:
    """读一个桌面应用的 AX 树;返回一次性元素令牌,不代表已经能操作它。"""
    target = _desktop_id(pid, "pid")
    answer = _host_call(DESKTOP_ACCESSIBILITY_CHANNEL, {"pid": target})
    elements = answer.get("elements")
    meta = answer.get("meta")
    if not isinstance(elements, list) or not isinstance(meta, dict):
        raise ComputerUseError("The desktop accessibility bridge answered without a valid AX snapshot.")
    return {"pid": target, "snapshot_id": str(meta.get("snapshot_id") or ""), "elements": elements}


def _protected_placeholder(width: int, height: int) -> bytes:
    """受保护窗口只给一块打码占位,不把真实像素交给模型或回放。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (max(1, width), max(1, height)), (24, 30, 40))
    draw = ImageDraw.Draw(image)
    text = "Protected window"
    box = draw.textbbox((0, 0), text)
    draw.text(
        ((width - (box[2] - box[0])) / 2, (height - (box[3] - box[1])) / 2),
        text,
        fill=(160, 170, 184),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _desktop_id(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ComputerUseError(f"{name} must be a positive integer from computer_desktop_windows.")
    return value


def _desktop_target(
    token: object, capture_id: object, x: object, y: object, scale: float
) -> dict[str, Any]:
    token_text = str(token or "").strip()
    capture_text = str(capture_id or "").strip()
    if bool(token_text) == bool(capture_text):
        raise ComputerUseError("Provide exactly one target: an element token, or capture_id with x and y.")
    if token_text:
        head, _, index = token_text.rpartition(":")
        if not head or not index.isdigit():
            raise ComputerUseError("The desktop element token is invalid; observe the app again.")
        return {"token": token_text}
    factor = _scale(scale)
    if x is None or y is None:
        raise ComputerUseError("capture_id needs both x and y in the screenshot you looked at.")
    return {
        "captureId": capture_text,
        "x": _screenshot_coordinate(x, "x", factor),
        "y": _screenshot_coordinate(y, "y", factor),
    }


def desktop_click(
    token: object = "",
    capture_id: object = "",
    x: object = None,
    y: object = None,
    button: object = "left",
    click_count: object = 1,
    scale: float = DEFAULT_SCALE,
    modifiers: object = None,
) -> dict[str, Any]:
    """点一下已验证的桌面目标;令牌或截图绑定由 Electron 驱动复核。"""
    target = _desktop_target(token, capture_id, x, y, scale)
    kind = str(button or "left").strip().lower()
    if kind not in CLICK_BUTTONS:
        raise ComputerUseError(f'button must be "left", "right" or "middle" (got {button!r}).')
    count = _desktop_click_count(click_count)
    mods = _modifiers(modifiers)
    _mark_touched()
    answer = _host_call(
        DESKTOP_CLICK_CHANNEL,
        {**target, "button": kind, "clickCount": count, "modifiers": mods},
    )
    if not isinstance(answer, dict) or not isinstance(answer.get("point"), dict):
        raise ComputerUseError("The desktop bridge answered without confirming the click.")
    return {**answer, "button": kind, "clickCount": count, "modifiers": mods}


def desktop_pointer(
    action: object,
    token: object = "",
    capture_id: object = "",
    x: object = None,
    y: object = None,
    button: object = "left",
    modifiers: object = None,
    scale: float = DEFAULT_SCALE,
) -> dict[str, Any]:
    """在已验证的桌面目标上 hover / 按下 / 抬起鼠标键;目标绑定仍是一次性的。"""
    kind = str(action or "").strip().lower()
    if kind not in L1_POINTER_ACTIONS:
        raise ComputerUseError('action must be "hover", "down" or "up".')
    target = _desktop_target(token, capture_id, x, y, scale)
    mouse = str(button or "left").strip().lower()
    if mouse not in CLICK_BUTTONS:
        raise ComputerUseError(f'button must be "left", "right" or "middle" (got {button!r}).')
    mods = _modifiers(modifiers)
    _mark_touched()
    answer = _host_call(DESKTOP_POINTER_CHANNEL, {
        **target, "action": kind, "button": mouse, "modifiers": mods,
    })
    if not isinstance(answer, dict) or answer.get("action") != kind:
        raise ComputerUseError("The desktop bridge answered without confirming the pointer action.")
    return {**answer, "action": kind, "button": mouse, "modifiers": mods}


def desktop_type(
    text: object = "",
    token: object = "",
    capture_id: object = "",
    x: object = None,
    y: object = None,
    scale: float = DEFAULT_SCALE,
    click_target: object = True,
) -> dict[str, Any]:
    """在已验证的桌面目标里输入文字;默认先点一下目标,`click_target=False` 时输入到当前焦点。"""
    if not isinstance(text, str) or not text:
        raise ComputerUseError("text must be a non-empty string; nothing was typed.")
    if len(text) > MAX_TYPE_CHARS:
        raise ComputerUseError(f"text must be at most {MAX_TYPE_CHARS} characters (got {len(text)}); nothing was typed.")
    target = _desktop_target(token, capture_id, x, y, scale)
    _mark_touched()
    answer = _host_call(
        DESKTOP_TYPE_CHANNEL,
        {**target, "text": text, "clickTarget": _bool_flag(click_target, "click_target")},
    )
    if not isinstance(answer, dict) or not isinstance(answer.get("point"), dict):
        raise ComputerUseError("The desktop bridge answered without confirming the typing.")
    return {**answer, "typed": len(text)}


def desktop_scroll(
    dy: object = 0,
    token: object = "",
    capture_id: object = "",
    x: object = None,
    y: object = None,
    scale: float = DEFAULT_SCALE,
    dx: object = 0,
) -> dict[str, Any]:
    """在已验证的桌面目标上滚动;dy > 0 向下、dx > 0 向右,最多各 30 格。"""
    vertical = _scroll_notches(dy, "dy")
    horizontal = _scroll_notches(dx, "dx")
    if vertical == 0 and horizontal == 0:
        raise ComputerUseError("dx or dy must be a non-zero integer.")
    target = _desktop_target(token, capture_id, x, y, scale)
    _mark_touched()
    answer = _host_call(DESKTOP_SCROLL_CHANNEL, {**target, "dy": vertical, "dx": horizontal})
    if not isinstance(answer, dict) or not isinstance(answer.get("point"), dict):
        raise ComputerUseError("The desktop bridge answered without confirming the scroll.")
    return {**answer, "dy": vertical, "dx": horizontal}


def desktop_drag(
    capture_id: object,
    from_x: object,
    from_y: object,
    to_x: object,
    to_y: object,
    button: object = "left",
    duration_ms: object = DEFAULT_DRAG_MS,
    scale: float = DEFAULT_SCALE,
) -> dict[str, Any]:
    """在一张桌面截图的绑定内从起点拖到终点;两个坐标都必须来自同一张截图。"""
    capture = str(capture_id or "").strip()
    if not capture:
        raise ComputerUseError("capture_id is required: drag both points in one computer_desktop_screenshot.")
    factor = _scale(scale)
    start_x = _screenshot_coordinate(from_x, "from_x", factor)
    start_y = _screenshot_coordinate(from_y, "from_y", factor)
    end_x = _screenshot_coordinate(to_x, "to_x", factor)
    end_y = _screenshot_coordinate(to_y, "to_y", factor)
    kind = _drag_button(button)
    duration = _drag_duration(duration_ms)
    _mark_touched()
    answer = _host_call(
        DESKTOP_DRAG_CHANNEL,
        {
            "captureId": capture,
            "fromX": start_x,
            "fromY": start_y,
            "toX": end_x,
            "toY": end_y,
            "button": kind,
            "durationMs": duration,
        },
    )
    if not isinstance(answer, dict) or not isinstance(answer.get("point"), dict):
        raise ComputerUseError("The desktop bridge answered without confirming the drag.")
    return {
        **answer,
        "from": {"x": start_x, "y": start_y},
        "to": {"x": end_x, "y": end_y},
        "button": kind,
        "durationMs": duration,
    }


def key_payload(key: object, modifiers: object) -> tuple[str, list[str]]:
    """归一化一个按键和一个组合键;拒绝任意字符串,避免把标记、路径之类塞进键盘事件。"""
    text = str(key or "").strip()
    lowered = text.lower()
    if len(lowered) == 1 and (lowered.isalnum() or lowered in "`-=[]\\;',./"):
        normalized = lowered
    elif lowered in SPECIAL_KEYS:
        normalized = {"return": "enter", "esc": "escape", "arrowleft": "left", "arrowright": "right",
                      "arrowup": "up", "arrowdown": "down"}.get(lowered, lowered)
    else:
        raise ComputerUseError(
            "key must be one letter/digit/punctuation key or a named key such as Enter, Tab, Escape, ArrowUp or F5."
        )
    if modifiers is None:
        mods: list[str] = []
    elif isinstance(modifiers, (list, tuple)):
        mods = [str(one).strip().lower() for one in modifiers if str(one).strip()]
    else:
        raise ComputerUseError("modifiers must be a list such as [\"cmd\", \"shift\"].")
    unsupported = [one for one in mods if one not in KEY_MODIFIERS]
    if unsupported:
        raise ComputerUseError(f"unsupported modifier(s): {', '.join(unsupported)}")
    return normalized, list(dict.fromkeys(mods))


def press(key: object, modifiers: object = None, hold_ms: object = 0) -> dict[str, Any]:
    """在 Mosael 主窗口里按一个键或组合键;`hold_ms` > 0 时按住这么久再松开。"""
    normalized, mods = key_payload(key, modifiers)
    hold = _hold_ms(hold_ms)
    _mark_touched()
    answer = _host_call(KEY_CHANNEL, {"key": normalized, "modifiers": mods, "holdMs": hold})
    if not isinstance(answer, dict):
        raise ComputerUseError("The Mosael window bridge answered without confirming the key press.")
    return {**answer, "key": normalized, "modifiers": mods, "holdMs": hold}


def desktop_press(
    key: object,
    modifiers: object = None,
    token: object = "",
    capture_id: object = "",
    x: object = None,
    y: object = None,
    scale: float = DEFAULT_SCALE,
    click_target: object = True,
    hold_ms: object = 0,
) -> dict[str, Any]:
    """在已验证的桌面目标上按一个键或组合键;`click_target=False` 时只聚焦应用,不点击元素。"""
    normalized, mods = key_payload(key, modifiers)
    hold = _hold_ms(hold_ms)
    target = _desktop_target(token, capture_id, x, y, scale)
    _mark_touched()
    answer = _host_call(
        DESKTOP_KEY_CHANNEL,
        {
            **target, "key": normalized, "modifiers": mods,
            "clickTarget": _bool_flag(click_target, "click_target"), "holdMs": hold,
        },
    )
    if not isinstance(answer, dict) or not isinstance(answer.get("point"), dict):
        raise ComputerUseError("The desktop bridge answered without confirming the key press.")
    return {**answer, "key": normalized, "modifiers": mods, "holdMs": hold}


def _mark_touched() -> None:
    global _touched_this_turn
    _touched_this_turn = True


def click(
    x: object = 0,
    y: object = 0,
    button: str = "left",
    click_count: object = 1,
    scale: float = DEFAULT_SCALE,
    token: object = "",
    modifiers: object = None,
) -> dict[str, Any]:
    """点一下 Mosael 主窗口。`x`/`y` 是图片像素;`token` 是截图元素清单里的一次性令牌。

    有 `token` 时不再用坐标:主进程会重读 DOM、核对元素仍在原处,然后点元素中心。
    """
    element = _element_token(token)
    kind = str(button or "left").strip().lower()
    if kind not in L1_BUTTONS:
        raise ComputerUseError(f'button must be "left", "right" or "middle" (got {button!r}).')
    count = _click_count(click_count)
    mods = _modifiers(modifiers)
    if element:
        _mark_touched()
        answer = _host_call(CLICK_CHANNEL, {
            "token": element, "button": kind, "clickCount": count, "modifiers": mods,
        })
        if not isinstance(answer, dict) or answer.get("x") is None:
            raise ComputerUseError("The Mosael window bridge answered without confirming the click.")
        return {**answer, "button": kind, "clickCount": count, "token": element}
    factor = _scale(scale)
    css_x = _screenshot_coordinate(x, "x", factor)
    css_y = _screenshot_coordinate(y, "y", factor)
    _mark_touched()
    answer = _host_call(CLICK_CHANNEL, {
        "x": css_x, "y": css_y, "button": kind, "clickCount": count, "modifiers": mods,
    })
    if not isinstance(answer, dict) or answer.get("x") is None:
        raise ComputerUseError("The Mosael window bridge answered without confirming the click.")
    return {
        "x": css_x, "y": css_y, "scale": factor, "button": kind, "clickCount": count, "modifiers": mods,
    }


def drag(
    from_x: object = 0,
    from_y: object = 0,
    to_x: object = 0,
    to_y: object = 0,
    button: object = "left",
    duration_ms: object = DEFAULT_DRAG_MS,
    scale: float = DEFAULT_SCALE,
    from_token: object = "",
    to_token: object = "",
) -> dict[str, Any]:
    """在 Mosael 主窗口里从起点拖到终点;也可给起点/终点元素 token。"""
    first = _element_token(from_token)
    last = _element_token(to_token)
    if bool(first) != bool(last):
        raise ComputerUseError("from_token and to_token must be provided together.")
    kind = _drag_button(button)
    duration = _drag_duration(duration_ms)
    if first and last:
        _mark_touched()
        answer = _host_call(DRAG_CHANNEL, {
            "fromToken": first, "toToken": last, "button": kind, "durationMs": duration,
        })
        if not isinstance(answer, dict) or answer.get("toX") is None:
            raise ComputerUseError("The Mosael window bridge answered without confirming the drag.")
        return {
            **answer, "fromToken": first, "toToken": last,
            "button": kind, "durationMs": duration,
        }
    factor = _scale(scale)
    start_x = _screenshot_coordinate(from_x, "from_x", factor)
    start_y = _screenshot_coordinate(from_y, "from_y", factor)
    end_x = _screenshot_coordinate(to_x, "to_x", factor)
    end_y = _screenshot_coordinate(to_y, "to_y", factor)
    _mark_touched()
    answer = _host_call(
        DRAG_CHANNEL,
        {
            "fromX": start_x,
            "fromY": start_y,
            "toX": end_x,
            "toY": end_y,
            "button": kind,
            "durationMs": duration,
        },
    )
    if not isinstance(answer, dict) or answer.get("toX") is None:
        raise ComputerUseError("The Mosael window bridge answered without confirming the drag.")
    return {
        **answer,
        "from": {"x": start_x, "y": start_y},
        "to": {"x": end_x, "y": end_y},
        "scale": factor,
        "button": kind,
        "durationMs": duration,
    }


def pointer(
    action: object,
    x: object,
    y: object,
    button: object = "left",
    modifiers: object = None,
    scale: float = DEFAULT_SCALE,
) -> dict[str, Any]:
    """在 Mosael 主窗口里移动指针或单独按下/抬起鼠标键。`action`: hover / down / up。"""
    kind = str(action or "").strip().lower()
    if kind not in L1_POINTER_ACTIONS:
        raise ComputerUseError('action must be "hover", "down" or "up".')
    mouse = str(button or "left").strip().lower()
    if mouse not in L1_BUTTONS:
        raise ComputerUseError(f'button must be "left", "right" or "middle" (got {button!r}).')
    factor = _scale(scale)
    css_x = _screenshot_coordinate(x, "x", factor)
    css_y = _screenshot_coordinate(y, "y", factor)
    mods = _modifiers(modifiers)
    _mark_touched()
    answer = _host_call(POINTER_CHANNEL, {
        "action": kind, "x": css_x, "y": css_y, "button": mouse, "modifiers": mods,
    })
    if not isinstance(answer, dict) or answer.get("action") != kind:
        raise ComputerUseError("The Mosael window bridge answered without confirming the pointer action.")
    return {
        **answer, "action": kind, "x": css_x, "y": css_y, "scale": factor,
        "button": mouse, "modifiers": mods,
    }


def type_text(text: object = "", token: object = "") -> dict[str, Any]:
    """往 Mosael 主窗口里输入一段文字;给 token 时先点该元素再输入。"""

    if not isinstance(text, str) or not text:
        raise ComputerUseError("text must be a non-empty string; nothing was typed.")
    if len(text) > MAX_TYPE_CHARS:
        raise ComputerUseError(f"text must be at most {MAX_TYPE_CHARS} characters (got {len(text)}); nothing was typed.")
    element = _element_token(token)
    _mark_touched()
    payload = {"text": text, **({"token": element} if element else {})}
    answer = _host_call(TYPE_CHANNEL, payload)
    if not isinstance(answer, dict) or answer.get("typed") != len(text):
        raise ComputerUseError("The Mosael window bridge answered without confirming the typing.")
    return {**({"token": element} if element else {}), "typed": len(text)}


def scroll(
    dy: object = 0,
    x: object = None,
    y: object = None,
    scale: float = DEFAULT_SCALE,
    dx: object = 0,
) -> dict[str, Any]:
    """在 Mosael 主窗口里滚动;`dy` 正 = 下,`dx` 正 = 右,至少一个非零。"""
    factor = _scale(scale)
    vertical = _scroll_notches(dy, "dy")
    horizontal = _scroll_notches(dx, "dx")
    if vertical == 0 and horizontal == 0:
        raise ComputerUseError("dx or dy must be a non-zero integer.")
    payload: dict[str, Any] = {"dy": vertical, "dx": horizontal}
    if x is not None:
        payload["x"] = _screenshot_coordinate(x, "x", factor)
    if y is not None:
        payload["y"] = _screenshot_coordinate(y, "y", factor)
    _mark_touched()
    answer = _host_call(SCROLL_CHANNEL, payload)
    if not isinstance(answer, dict) or answer.get("dy") != vertical or answer.get("dx") != horizontal:
        raise ComputerUseError("The Mosael window bridge answered without confirming the scroll.")
    return {
        "dy": vertical, "dx": horizontal, "scale": factor, "x": payload.get("x"), "y": payload.get("y"),
    }


def _screenshot_coordinate(value: object, axis: str, factor: float) -> int:
    """图片像素 → 窗口 CSS 像素。整数、非负;缩放过的图除回去(并接受模型给的图坐标)。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComputerUseError(f"{axis} must be a number: the pixel column/row in the screenshot you looked at.")
    pixels = float(value)
    if not math.isfinite(pixels) or pixels < 0:
        raise ComputerUseError(f"{axis} must be a non-negative number (got {value!r}).")
    return max(0, round(pixels / factor))


def _click_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) not in (1, 2, 3):
        raise ComputerUseError(f"click_count must be 1 (single), 2 (double) or 3 (triple), not {value!r}.")
    return int(value)


def _desktop_click_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) not in (1, 2, 3):
        raise ComputerUseError(f"click_count must be 1 (single), 2 (double) or 3 (triple), not {value!r}.")
    return int(value)


def _scroll_notches(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComputerUseError(f"{name} must be a number of wheel notches (got {value!r}).")
    notches = int(value)
    if abs(notches) > MAX_SCROLL_NOTCHES:
        raise ComputerUseError(f"{name} must be between -{MAX_SCROLL_NOTCHES} and {MAX_SCROLL_NOTCHES}.")
    return notches


def _modifiers(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ComputerUseError("modifiers must be a list such as [\"shift\", \"ctrl\"].")
    mods = [str(one).strip().lower() for one in value if str(one).strip()]
    unsupported = [one for one in mods if one not in KEY_MODIFIERS]
    if unsupported:
        raise ComputerUseError(f"unsupported modifier(s): {', '.join(unsupported)}")
    return list(dict.fromkeys(mods))


def _hold_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComputerUseError("hold_ms must be a number of milliseconds.")
    hold = int(value)
    if hold < 0 or hold > MAX_HOLD_MS:
        raise ComputerUseError(f"hold_ms must be between 0 and {MAX_HOLD_MS}.")
    return hold


def _element_token(value: object) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}:\d{1,8}", token):
        raise ComputerUseError("The element token is invalid; take a new screenshot.")
    return token


def _drag_button(value: object) -> str:
    kind = str(value or "left").strip().lower()
    if kind not in CLICK_BUTTONS:
        raise ComputerUseError(f'button must be "left" or "right" (got {value!r}).')
    return kind


def _drag_duration(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComputerUseError(f"duration_ms must be a number between {MIN_DRAG_MS} and {MAX_DRAG_MS}.")
    duration = int(value)
    if duration < MIN_DRAG_MS or duration > MAX_DRAG_MS:
        raise ComputerUseError(
            f"duration_ms must be between {MIN_DRAG_MS} and {MAX_DRAG_MS} (got {value!r})."
        )
    return duration


def _bool_flag(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ComputerUseError(f"{name} must be true or false.")
    return value


def _wait_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ComputerUseError("text must be a non-empty string to wait for.")
    if len(text) > 200:
        raise ComputerUseError("text to wait for must be at most 200 characters.")
    return text


def _wait_timeout(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComputerUseError(f"timeout_ms must be a number between {MIN_WAIT_MS} and {MAX_WAIT_MS}.")
    timeout = int(value)
    if timeout < MIN_WAIT_MS or timeout > MAX_WAIT_MS:
        raise ComputerUseError(
            f"timeout_ms must be between {MIN_WAIT_MS} and {MAX_WAIT_MS} (got {value!r})."
        )
    return timeout


#: 这一轮里动过手没有(点/输入/滚动成功过一次就记上)。回合结束时据此决定要不要提醒桌面壳 ——
#: 每一轮都发一条桥消息也没坏处,但「没动过」的回合根本不需要问对面。
_touched_this_turn = False


def end_turn() -> None:
    """一次智能体回合结束:如果这一轮动过手,告诉桌面壳「被控制中」可以熄了。

    **不是急停**:不设 stopped,下一轮还能动。桥不在(独立后端 / 远程部署)时静默跳过 ——
    回合收尾不该因为一条提示通道不在而失败。
    """
    global _touched_this_turn
    if not _touched_this_turn:
        return
    _touched_this_turn = False
    try:
        _host_call(END_CHANNEL, {})
    except ComputerUseError:
        pass


def _region(value: object) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ComputerUseError("region must be [x0, y0, x1, y1] in full-screenshot pixels.")
    coords: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ComputerUseError("region must be [x0, y0, x1, y1] in full-screenshot pixels.")
        coords.append(max(0, round(float(item))))
    x0, y0, x1, y1 = coords
    if x1 <= x0 or y1 <= y0:
        raise ComputerUseError("region needs x1 > x0 and y1 > y0.")
    return x0, y0, x1, y1


def _scale(value: object) -> float:
    # bool 是 int 的子类:True 不是 1 倍,是「模型把话听拧了」。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComputerUseError(
            f"scale must be a number between {MIN_SCALE} and {MAX_SCALE}, not {value!r}. "
            "Leave it empty for 1 (the window's own size)."
        )
    factor = float(value)
    if not math.isfinite(factor) or not MIN_SCALE <= factor <= MAX_SCALE:
        raise ComputerUseError(
            f"scale must be between {MIN_SCALE} and {MAX_SCALE} (got {factor}). "
            "Leave it empty for 1; use a smaller number only to shrink a large window."
        )
    return factor


def _image_bytes(answer: dict[str, Any]) -> bytes:
    encoded = answer.get("image")
    if not isinstance(encoded, str) or not encoded.strip():
        raise ComputerUseError("The Mosael window returned no picture; nothing to show.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ComputerUseError("The Mosael window returned a picture that isn't valid base64.") from None
    if not raw:
        raise ComputerUseError("The Mosael window returned an empty picture; nothing to show.")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ComputerUseError("The Mosael window returned a picture that is too large to show.")
    return raw


def _size_and_pixels(raw: bytes, factor: float) -> tuple[int, int, bytes]:
    """读出真实尺寸;`scale < 1` 时把图缩小(只有这一步需要解码 PNG)。

    尺寸以**图片本身**为准,不以对面报的数字为准 —— 缩过的图必须回缩小后的宽高,模型据此
    判断自己在看的是整窗还是缩略图。
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG":
                raise ComputerUseError(f"The Mosael window returned {image.format or 'something'}, not a PNG.")
            width, height = image.size
            if factor >= MAX_SCALE:
                return width, height, raw
            target = (max(1, round(width * factor)), max(1, round(height * factor)))
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            resized = image.resize(target, Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG")
            return target[0], target[1], buffer.getvalue()
    except ComputerUseError:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise ComputerUseError("The Mosael window returned something that isn't a readable PNG.") from None


def _scaled_elements(value: object, factor: float) -> list[dict[str, Any]]:
    """把 Electron 交回的 CSS 坐标元素清单缩到模型看到的那张图上;形状不对的条目丢掉。"""
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for row in value[:200]:
        if not isinstance(row, dict):
            continue
        clean: dict[str, Any] = {
            "role": str(row.get("role") or "")[:40],
            "name": str(row.get("name") or "")[:120],
            "disabled": bool(row.get("disabled")),
        }
        token = str(row.get("token") or "")[:120]
        if token:
            clean["token"] = token
        for key in ("x", "y", "width", "height"):
            number = row.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                clean = {}
                break
            clean[key] = max(0, round(float(number) * factor))
        if clean:
            out.append(clean)
    return out


def _bridge_endpoint() -> tuple[int, str]:
    """桥的地址与令牌:先看进程环境,再看数据目录里的 `host-bridge.json`。

    两条都要,因为后端的起法有两种:壳拉起的那个可以走环境变量,而 `pnpm dev:backend` 单独起的
    那个只能按**同一个数据目录**找到壳写下的文件。两边都没有 = 这个后端不在桌面壳里跑
    (远程团队服务器),截图能力就不存在 —— 这不是错误配置,是一句要跟模型说清楚的事实。
    """
    port_text = os.environ.get(BRIDGE_PORT_ENV, "").strip()
    token = os.environ.get(BRIDGE_TOKEN_ENV, "").strip()
    if not port_text or not token:

        try:
            saved = json.loads((settings.data_dir / BRIDGE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict):
            port_text = str(saved.get("port") or "").strip()
            token = str(saved.get("token") or "").strip()
    if not port_text or not token:
        raise ComputerUseError(
            "computer_screenshot only works in the Mosael desktop app: its window bridge isn't running "
            "for this backend. Nothing was captured."
        )
    try:
        port = int(port_text)
    except ValueError:
        raise ComputerUseError("The Mosael window bridge address is invalid; nothing was captured.") from None
    if not 0 < port < 65536:
        raise ComputerUseError("The Mosael window bridge address is invalid; nothing was captured.")
    return port, token


def _host_call(channel: str, payload: dict[str, Any]) -> dict[str, Any]:
    """经回环桥问 Electron 主进程一次。测试里替换的就是这一个函数(替身返回一张 PNG)。"""
    port, token = _bridge_endpoint()

    request = json.dumps({"token": token, "channel": channel, "payload": payload}, ensure_ascii=False)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT_SECONDS) as connection:
            connection.settimeout(READ_TIMEOUT_SECONDS)
            connection.sendall(request.encode("utf-8") + b"\n")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_MESSAGE_BYTES:
                    raise ComputerUseError("The Mosael window bridge answered with too much data.")
                if b"\n" in chunk:
                    break
    except ComputerUseError:
        raise
    except OSError:
        raise ComputerUseError(
            "Couldn't reach the Mosael desktop app to take the screenshot. Is the app still running? "
            "Nothing was captured."
        ) from None

    payload_bytes = b"".join(chunks).split(b"\n", 1)[0]
    if not payload_bytes:
        raise ComputerUseError("The Mosael window bridge closed without answering; nothing was captured.")
    try:
        answer = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ComputerUseError("The Mosael window bridge answered with something that isn't JSON.") from None
    if not isinstance(answer, dict) or not answer.get("ok"):
        message = answer.get("error") if isinstance(answer, dict) else ""
        raise ComputerUseError(str(message or "The Mosael window couldn't be captured."))
    result = answer.get("result")
    if not isinstance(result, dict):
        raise ComputerUseError("The Mosael window bridge answered without a picture.")
    return result


__all__ = [
    "CLICK_BUTTONS",
    "CLICK_CHANNEL",
    "CLIPBOARD_READ_CHANNEL",
    "OCR_CHANNEL",
    "CLIPBOARD_WRITE_CHANNEL",
    "ComputerUseError",
    "L1_BUTTONS",
    "L1_POINTER_ACTIONS",
    "MAX_HOLD_MS",
    "POINTER_CHANNEL",
    "DEFAULT_DRAG_MS",
    "DEFAULT_SCALE",
    "DEFAULT_WAIT_MS",
    "DESKTOP_WAIT_CHANNEL",
    "DESKTOP_VERIFY_CHANNEL",
    "DRAG_CHANNEL",
    "END_CHANNEL",
    "MAX_WAIT_MS",
    "MIN_WAIT_MS",
    "WAIT_CHANNEL",
    "VERIFY_CHANNEL",
    "MAX_DRAG_MS",
    "MAX_SCALE",
    "MIN_DRAG_MS",
    "MIN_SCALE",
    "SCREENSHOT_CHANNEL",
    "DESKTOP_ACCESSIBILITY_CHANNEL",
    "DESKTOP_CLICK_CHANNEL",
    "DESKTOP_POINTER_CHANNEL",
    "DESKTOP_DRAG_CHANNEL",
    "DESKTOP_FULL_SCREENSHOT_CHANNEL",
    "DESKTOP_OCR_CHANNEL",
    "DESKTOP_SCREENSHOT_CHANNEL",
    "DESKTOP_SCROLL_CHANNEL",
    "DESKTOP_TYPE_CHANNEL",
    "DESKTOP_WINDOWS_CHANNEL",
    "SCROLL_CHANNEL",
    "TYPE_CHANNEL",
    "click",
    "clipboard_read",
    "clipboard_write",
    "drag",
    "pointer",
    "end_turn",
    "desktop_accessibility",
    "desktop_click",
    "desktop_drag",
    "desktop_full_screenshot",
    "desktop_ocr",
    "desktop_pointer",
    "desktop_screenshot",
    "desktop_scroll",
    "desktop_type",
    "desktop_verify",
    "desktop_wait",
    "desktop_windows",
    "screenshot",
    "scroll",
    "type_text",
    "verify",
    "wait",
    "zoom",
]
