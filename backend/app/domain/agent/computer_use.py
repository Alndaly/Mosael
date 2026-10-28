"""Computer Use 的宿主桥:L1 操作 Mosael 自己,L3 只读观察桌面(ADR 0075 / 0081)。

L1 图由 Electron 用 `webContents.capturePage()` 拍 Mosael 自己的渲染,不需要屏幕录制权限;
L3 由 DesktopDriverMac 枚举其他应用窗口、截图和读取 AX 树,桌面输入尚未开放。

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
DESKTOP_ACCESSIBILITY_CHANNEL = "computer:desktop-accessibility"
DESKTOP_CLICK_CHANNEL = "computer:desktop-click"
DESKTOP_TYPE_CHANNEL = "computer:desktop-type"
DESKTOP_SCROLL_CHANNEL = "computer:desktop-scroll"
#: 动手:L1 的点击与输入(ADR 0075 的 P1)。坐标是**看着的那张图**上的(缩放过的)像素,
#: 这里除以 scale 换成窗口的 CSS 像素再交给主进程 —— 模型不需要知道缩放这回事。
CLICK_CHANNEL = "computer:click"
TYPE_CHANNEL = "computer:type"
SCROLL_CHANNEL = "computer:scroll"
#: 这一轮结束了 —— 让主进程把「被控制中」熄灭(不是急停:下一轮还能动)。
END_CHANNEL = "computer:end"
#: 一次滚动最多几格滚轮。再多就不是「往下看看」,而是整段跳走。
MAX_SCROLL_NOTCHES = 30

#: 能点的键。
CLICK_BUTTONS = ("left", "right")
#: 一次最多输入这么多字符。再多就不是「在输入框里写一句话」,而是整段粘贴了。
MAX_TYPE_CHARS = 2000

#: 这些应用即使只读截图也不把像素交出去(与 Electron 驱动的动作黑名单对齐)。
PROTECTED_OWNERS = frozenset({
    "1Password", "1Password 7", "Bitwarden", "Dashlane", "Keeper", "KeePassXC",
    "Keychain Access", "钥匙串访问", "Passwords", "密码", "SecurityAgent",
    "System Settings", "System Preferences", "系统设置", "系统偏好设置",
    "Terminal", "终端", "iTerm2", "Warp", "loginwindow",
})


class ComputerUseError(ValueError):
    """给模型看的一句话。不是 traceback,也不是 HTTP 500 —— 模型据此改参数或告诉用户。"""


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
) -> dict[str, Any]:
    """点一下已验证的桌面目标;令牌或截图绑定由 Electron 驱动复核。"""
    target = _desktop_target(token, capture_id, x, y, scale)
    kind = str(button or "left").strip().lower()
    if kind not in CLICK_BUTTONS:
        raise ComputerUseError(f'button must be "left" or "right" (got {button!r}).')
    count = _click_count(click_count)
    _mark_touched()
    answer = _host_call(DESKTOP_CLICK_CHANNEL, {**target, "button": kind, "clickCount": count})
    if not isinstance(answer, dict) or not isinstance(answer.get("point"), dict):
        raise ComputerUseError("The desktop bridge answered without confirming the click.")
    return {**answer, "button": kind, "clickCount": count}


def desktop_type(
    text: object = "",
    token: object = "",
    capture_id: object = "",
    x: object = None,
    y: object = None,
    scale: float = DEFAULT_SCALE,
) -> dict[str, Any]:
    """在已验证的桌面目标里输入文字;只输入这一串,不按额外快捷键。"""
    if not isinstance(text, str) or not text:
        raise ComputerUseError("text must be a non-empty string; nothing was typed.")
    if len(text) > MAX_TYPE_CHARS:
        raise ComputerUseError(f"text must be at most {MAX_TYPE_CHARS} characters (got {len(text)}); nothing was typed.")
    target = _desktop_target(token, capture_id, x, y, scale)
    _mark_touched()
    answer = _host_call(DESKTOP_TYPE_CHANNEL, {**target, "text": text})
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
) -> dict[str, Any]:
    """在已验证的桌面目标上滚动;dy > 0 向下,最多 30 格。"""
    if isinstance(dy, bool) or not isinstance(dy, (int, float)):
        raise ComputerUseError(f"dy must be a number of wheel notches (got {dy!r}).")
    notches = int(dy)
    if notches == 0 or abs(notches) > MAX_SCROLL_NOTCHES:
        raise ComputerUseError(f"dy must be a non-zero integer between -{MAX_SCROLL_NOTCHES} and {MAX_SCROLL_NOTCHES}.")
    target = _desktop_target(token, capture_id, x, y, scale)
    _mark_touched()
    answer = _host_call(DESKTOP_SCROLL_CHANNEL, {**target, "dy": notches})
    if not isinstance(answer, dict) or not isinstance(answer.get("point"), dict):
        raise ComputerUseError("The desktop bridge answered without confirming the scroll.")
    return {**answer, "dy": notches}


def _mark_touched() -> None:
    global _touched_this_turn
    _touched_this_turn = True


def click(
    x: object = 0,
    y: object = 0,
    button: str = "left",
    click_count: object = 1,
    scale: float = DEFAULT_SCALE,
) -> dict[str, Any]:
    """点一下 Mosael 主窗口。`x`/`y` 是**图片上**的像素(=窗口 CSS 像素 × scale)。

    返回实际点到的 CSS 坐标与缩放,模型据此核对「我刚才看的那张图」和这次动作是同一个坐标系。
    """
    factor = _scale(scale)
    css_x = _screenshot_coordinate(x, "x", factor)
    css_y = _screenshot_coordinate(y, "y", factor)
    kind = str(button or "left").strip().lower()
    if kind not in CLICK_BUTTONS:
        raise ComputerUseError(f'button must be "left" or "right" (got {button!r}).')
    count = _click_count(click_count)
    _mark_touched()
    answer = _host_call(CLICK_CHANNEL, {"x": css_x, "y": css_y, "button": kind, "clickCount": count})
    if not isinstance(answer, dict) or answer.get("x") is None:
        raise ComputerUseError("The Mosael window bridge answered without confirming the click.")
    return {"x": css_x, "y": css_y, "scale": factor, "button": kind, "clickCount": count}


def type_text(text: object = "") -> dict[str, Any]:
    """往 Mosael 主窗口里输入一段文字(输入到当前焦点)。"""

    if not isinstance(text, str) or not text:
        raise ComputerUseError("text must be a non-empty string; nothing was typed.")
    if len(text) > MAX_TYPE_CHARS:
        raise ComputerUseError(f"text must be at most {MAX_TYPE_CHARS} characters (got {len(text)}); nothing was typed.")
    _mark_touched()
    answer = _host_call(TYPE_CHANNEL, {"text": text})
    if not isinstance(answer, dict) or answer.get("typed") != len(text):
        raise ComputerUseError("The Mosael window bridge answered without confirming the typing.")
    return {"typed": len(text)}


def scroll(
    dy: object = 0,
    x: object = None,
    y: object = None,
    scale: float = DEFAULT_SCALE,
) -> dict[str, Any]:
    """在 Mosael 主窗口里滚动。`dy` 是滚轮格数(正 = 往下);`x`/`y` 是在图片上的指针位置(可省)。"""
    factor = _scale(scale)
    if isinstance(dy, bool) or not isinstance(dy, (int, float)):
        raise ComputerUseError(f"dy must be a number of wheel notches (got {dy!r}).")
    notches = int(dy)
    if notches == 0 or abs(notches) > MAX_SCROLL_NOTCHES:
        raise ComputerUseError(f"dy must be a non-zero integer between -{MAX_SCROLL_NOTCHES} and {MAX_SCROLL_NOTCHES}.")
    payload: dict[str, Any] = {"dy": notches}
    if x is not None:
        payload["x"] = _screenshot_coordinate(x, "x", factor)
    if y is not None:
        payload["y"] = _screenshot_coordinate(y, "y", factor)
    _mark_touched()
    answer = _host_call(SCROLL_CHANNEL, payload)
    if not isinstance(answer, dict) or answer.get("dy") != notches:
        raise ComputerUseError("The Mosael window bridge answered without confirming the scroll.")
    return {"dy": notches, "scale": factor, "x": payload.get("x"), "y": payload.get("y")}


def _screenshot_coordinate(value: object, axis: str, factor: float) -> int:
    """图片像素 → 窗口 CSS 像素。整数、非负;缩放过的图除回去(并接受模型给的图坐标)。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComputerUseError(f"{axis} must be a number: the pixel column/row in the screenshot you looked at.")
    pixels = float(value)
    if not math.isfinite(pixels) or pixels < 0:
        raise ComputerUseError(f"{axis} must be a non-negative number (got {value!r}).")
    return max(0, round(pixels / factor))


def _click_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) not in (1, 2):
        raise ComputerUseError(f"click_count must be 1 (single) or 2 (double), not {value!r}.")
    return int(value)


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
    "ComputerUseError",
    "DEFAULT_SCALE",
    "END_CHANNEL",
    "MAX_SCALE",
    "MIN_SCALE",
    "SCREENSHOT_CHANNEL",
    "DESKTOP_ACCESSIBILITY_CHANNEL",
    "DESKTOP_CLICK_CHANNEL",
    "DESKTOP_SCREENSHOT_CHANNEL",
    "DESKTOP_SCROLL_CHANNEL",
    "DESKTOP_TYPE_CHANNEL",
    "DESKTOP_WINDOWS_CHANNEL",
    "SCROLL_CHANNEL",
    "TYPE_CHANNEL",
    "click",
    "end_turn",
    "desktop_accessibility",
    "desktop_click",
    "desktop_screenshot",
    "desktop_scroll",
    "desktop_type",
    "desktop_windows",
    "screenshot",
    "scroll",
    "type_text",
]
