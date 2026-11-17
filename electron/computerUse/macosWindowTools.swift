import Foundation
import CoreGraphics
import ApplicationServices
import AppKit

// ADR 0081: macOS 只读观察(P1)与受控桌面动作(P2)。
// 动作必须经 AX 权限;受保护应用与令牌校验在驱动层完成,这里只执行已验证的坐标与动作。

struct WindowJSON {
    static func write(_ value: Any) {
        guard let data = try? JSONSerialization.data(withJSONObject: value),
              let text = String(data: data, encoding: .utf8) else {
            FileHandle.standardError.write(Data("json encoding failed\n".utf8))
            exit(2)
        }
        print(text)
    }
}

func listWindows() -> [[String: Any]] {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
        return []
    }
    var result: [[String: Any]] = []
    for item in raw {
        guard let number = item[kCGWindowNumber as String] as? NSNumber else { continue }
        let bounds = item[kCGWindowBounds as String] as? [String: NSNumber] ?? [:]
        result.append([
            "id": number.uint32Value,
            "owner": item[kCGWindowOwnerName as String] as? String ?? "",
            "pid": (item[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value ?? 0,
            "title": item[kCGWindowName as String] as? String ?? "",
            "x": bounds["X"]?.doubleValue ?? 0,
            "y": bounds["Y"]?.doubleValue ?? 0,
            "width": bounds["Width"]?.doubleValue ?? 0,
            "height": bounds["Height"]?.doubleValue ?? 0,
            "layer": (item[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 0,
            "alpha": (item[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1,
            "onscreen": (item[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue ?? false,
        ])
    }
    return result
}


func stringAttribute(_ element: AXUIElement, _ name: String) -> String {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return "" }
    return value as? String ?? ""
}

func frameAttributes(_ element: AXUIElement) -> [String: Double] {
    var frame: [String: Double] = [:]
    var position: CFTypeRef?
    if AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &position) == .success, let value = position {
        var point = CGPoint.zero
        if AXValueGetValue(value as! AXValue, .cgPoint, &point) {
            frame["x"] = point.x
            frame["y"] = point.y
        }
    }
    var size: CFTypeRef?
    if AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &size) == .success, let value = size {
        var sizeValue = CGSize.zero
        if AXValueGetValue(value as! AXValue, .cgSize, &sizeValue) {
            frame["width"] = sizeValue.width
            frame["height"] = sizeValue.height
        }
    }
    return frame
}

func accessibilityTree(_ pid: Int32) -> [String: Any] {
    let application = AXUIElementCreateApplication(pid)
    let snapshot = UUID().uuidString
    var index = 0
    var elements: [[String: Any]] = []
    func walk(_ element: AXUIElement, path: [Int], depth: Int) {
        if depth > 10 || elements.count >= 400 { return }
        let identifier = "\(snapshot):\(index)"
        index += 1
        var node: [String: Any] = [
            "id": identifier,
            "path": path.map(String.init).joined(separator: "."),
            "role": stringAttribute(element, kAXRoleAttribute),
            "title": stringAttribute(element, kAXTitleAttribute),
        ]
        let value = stringAttribute(element, kAXValueAttribute)
        if !value.isEmpty { node["value"] = String(value.prefix(500)) }
        let frame = frameAttributes(element)
        if !frame.isEmpty { node["frame"] = frame }
        elements.append(node)
        var children: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &children) == .success,
              let list = children as? [AXUIElement] else { return }
        for (childIndex, child) in list.prefix(80).enumerated() {
            walk(child, path: path + [childIndex], depth: depth + 1)
        }
    }
    var rootChildren: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(application, kAXChildrenAttribute as CFString, &rootChildren)
    if result != .success {
        return ["error": ["code": result.rawValue, "message": "AXUIElementCopyAttributeValue failed: \(result)"]]
    }
    walk(application, path: [0], depth: 0)
    return ["snapshot_id": snapshot, "elements": elements]
}

func permissionStatus() -> [String: Bool] {
    return [
        "accessibility": AXIsProcessTrusted(),
        "screen": CGPreflightScreenCaptureAccess(),
    ]
}

/// 只有用户点了「向系统申请」才走到这里;状态查询绝不触发系统弹窗。
func requestPermission(_ kind: String) -> Bool {
    switch kind {
    case "accessibility":
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    case "screen":
        return CGRequestScreenCaptureAccess()
    default:
        FileHandle.standardError.write(Data("unknown permission: \(kind)\n".utf8))
        exit(2)
    }
}

func postClick(_ point: CGPoint, button: CGMouseButton, count: Int) {
    let downType: CGEventType = button == .right ? .rightMouseDown : .leftMouseDown
    let upType: CGEventType = button == .right ? .rightMouseUp : .leftMouseUp
    for click in 1...max(1, count) {
        if let down = CGEvent(mouseEventSource: nil, mouseType: downType, mouseCursorPosition: point, mouseButton: button) {
            down.setIntegerValueField(.mouseEventClickState, value: Int64(click))
            down.post(tap: .cghidEventTap)
        }
        if let up = CGEvent(mouseEventSource: nil, mouseType: upType, mouseCursorPosition: point, mouseButton: button) {
            up.setIntegerValueField(.mouseEventClickState, value: Int64(click))
            up.post(tap: .cghidEventTap)
        }
    }
}

func postDrag(from: CGPoint, to: CGPoint, button: CGMouseButton, durationMs: Int) {
    let downType: CGEventType = button == .right ? .rightMouseDown : .leftMouseDown
    let dragType: CGEventType = button == .right ? .rightMouseDragged : .leftMouseDragged
    let upType: CGEventType = button == .right ? .rightMouseUp : .leftMouseUp
    if let down = CGEvent(mouseEventSource: nil, mouseType: downType, mouseCursorPosition: from, mouseButton: button) {
        down.setIntegerValueField(.mouseEventClickState, value: 1)
        down.post(tap: .cghidEventTap)
    }
    let steps = max(8, min(30, durationMs / 20))
    let delay = Double(max(1, durationMs)) / 1000.0 / Double(steps + 1)
    for index in 1...steps {
        let progress = CGFloat(index) / CGFloat(steps + 1)
        let point = CGPoint(
            x: from.x + (to.x - from.x) * progress,
            y: from.y + (to.y - from.y) * progress
        )
        if let drag = CGEvent(mouseEventSource: nil, mouseType: dragType, mouseCursorPosition: point, mouseButton: button) {
            drag.setIntegerValueField(.mouseEventClickState, value: 1)
            drag.post(tap: .cghidEventTap)
        }
        Thread.sleep(forTimeInterval: delay)
    }
    if let up = CGEvent(mouseEventSource: nil, mouseType: upType, mouseCursorPosition: to, mouseButton: button) {
        up.setIntegerValueField(.mouseEventClickState, value: 1)
        up.post(tap: .cghidEventTap)
    }
}

func postUnicode(_ characters: [UniChar]) {
    guard !characters.isEmpty else { return }
    var buffer = characters
    if let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true) {
        down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: &buffer)
        down.post(tap: .cghidEventTap)
    }
    if let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false) {
        up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: &buffer)
        up.post(tap: .cghidEventTap)
    }
}

let keyCodes: [String: CGKeyCode] = [
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41,
    "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
    "enter": 36, "tab": 48, "space": 49, "backspace": 51, "escape": 53,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121, "delete": 117,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111
]

func postKey(_ key: String, modifiers: [String]) throws {
    guard let code = keyCodes[key.lowercased()] else {
        throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "unsupported key: \(key)"])
    }
    var flags: CGEventFlags = []
    for modifier in modifiers {
        switch modifier.lowercased() {
        case "cmd", "meta": flags.insert(.maskCommand)
        case "ctrl": flags.insert(.maskControl)
        case "alt": flags.insert(.maskAlternate)
        case "shift": flags.insert(.maskShift)
        default:
            throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "unsupported modifier: \(modifier)"])
        }
    }
    if let down = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true) {
        down.flags = flags
        down.post(tap: .cghidEventTap)
    }
    if let up = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false) {
        up.flags = flags
        up.post(tap: .cghidEventTap)
    }
}

func postText(_ text: String) {
    let units = Array(text.utf16)
    var index = 0
    while index < units.count {
        if units[index] == 10 {
            if let down = CGEvent(keyboardEventSource: nil, virtualKey: 36, keyDown: true) { down.post(tap: .cghidEventTap) }
            if let up = CGEvent(keyboardEventSource: nil, virtualKey: 36, keyDown: false) { up.post(tap: .cghidEventTap) }
            index += 1
            continue
        }
        var chunk: [UniChar] = []
        while index < units.count, units[index] != 10, chunk.count < 16 {
            chunk.append(units[index])
            index += 1
        }
        postUnicode(chunk)
    }
}

func activate(_ pid: Int32) throws {
    guard let app = NSRunningApplication(processIdentifier: pid) else {
        throw NSError(domain: "MosaelWindowTools", code: 404, userInfo: [NSLocalizedDescriptionKey: "app not found: \(pid)"])
    }
    if !app.activate(options: [.activateAllWindows]) {
        throw NSError(domain: "MosaelWindowTools", code: 503, userInfo: [NSLocalizedDescriptionKey: "could not focus app: \(pid)"])
    }
    Thread.sleep(forTimeInterval: 0.15)
}

/// 真输入前确认这个点所在的最上层窗口就是目标 App。菜单栏(y ≤ 40)单独放行。
func targetIsFrontmost(_ pid: Int32, _ point: CGPoint) -> Bool {
    if point.y <= 40 { return true }
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else { return false }
    for item in raw {
        guard let layer = (item[kCGWindowLayer as String] as? NSNumber)?.intValue, layer == 0,
              let bounds = item[kCGWindowBounds as String] as? [String: NSNumber] else { continue }
        let frame = CGRect(
            x: bounds["X"]?.doubleValue ?? 0,
            y: bounds["Y"]?.doubleValue ?? 0,
            width: bounds["Width"]?.doubleValue ?? 0,
            height: bounds["Height"]?.doubleValue ?? 0
        )
        if frame.contains(point) {
            return (item[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid
        }
    }
    return false
}

func performAction(_ request: [String: Any]) throws -> [String: Any] {
    guard let action = request["action"] as? String else {
        throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "action is required"])
    }
    guard let pidNumber = request["pid"] as? NSNumber else {
        throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "pid is required"])
    }
    let pid = pidNumber.int32Value
    guard let pointObject = request["point"] as? [String: Any],
          let x = (pointObject["x"] as? NSNumber)?.doubleValue,
          let y = (pointObject["y"] as? NSNumber)?.doubleValue else {
        throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "point is required"])
    }
    let point = CGPoint(x: x, y: y)
    let clickTarget = (request["clickTarget"] as? NSNumber)?.boolValue ?? true
    try activate(pid)
    guard targetIsFrontmost(pid, point) else {
        throw NSError(domain: "MosaelWindowTools", code: 409, userInfo: [NSLocalizedDescriptionKey: "the target window is not frontmost; nothing was sent"])
    }
    var dragEnd: CGPoint? = nil
    switch action {
    case "click":
        let buttonName = request["button"] as? String ?? "left"
        let button: CGMouseButton = buttonName == "right" ? .right : .left
        let count = max(1, min(2, (request["clickCount"] as? NSNumber)?.intValue ?? 1))
        postClick(point, button: button, count: count)
    case "type":
        guard let text = request["text"] as? String, !text.isEmpty else {
            throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "text is required"])
        }
        if clickTarget {
            postClick(point, button: .left, count: 1)
            Thread.sleep(forTimeInterval: 0.08)
        }
        postText(text)
    case "key":
        guard let key = request["key"] as? String, !key.isEmpty else {
            throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "key is required"])
        }
        let modifiers = request["modifiers"] as? [String] ?? []
        if clickTarget {
            postClick(point, button: .left, count: 1)
            Thread.sleep(forTimeInterval: 0.08)
        }
        try postKey(key, modifiers: modifiers)
    case "drag":
        guard let toPointObject = request["toPoint"] as? [String: Any],
              let toX = (toPointObject["x"] as? NSNumber)?.doubleValue,
              let toY = (toPointObject["y"] as? NSNumber)?.doubleValue else {
            throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "toPoint is required"])
        }
        let toPoint = CGPoint(x: toX, y: toY)
        guard targetIsFrontmost(pid, toPoint) else {
            throw NSError(domain: "MosaelWindowTools", code: 409, userInfo: [NSLocalizedDescriptionKey: "the drag end is not over the target app; nothing was sent"])
        }
        let buttonName = request["button"] as? String ?? "left"
        let button: CGMouseButton = buttonName == "right" ? .right : .left
        let duration = max(100, min(2000, (request["durationMs"] as? NSNumber)?.intValue ?? 300))
        postDrag(from: point, to: toPoint, button: button, durationMs: duration)
        dragEnd = toPoint
    case "scroll":
        guard let dy = (request["dy"] as? NSNumber)?.int32Value, dy != 0 else {
            throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "dy is required"])
        }
        if let move = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left) {
            move.post(tap: .cghidEventTap)
        }
        if let scroll = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: dy * 20, wheel2: 0, wheel3: 0) {
            scroll.location = point
            scroll.post(tap: .cghidEventTap)
        }
    default:
        throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "unknown action: \(action)"])
    }
    if let dragEnd {
        return ["ok": true, "action": action, "point": ["x": x, "y": y], "toPoint": [
            "x": dragEnd.x,
            "y": dragEnd.y,
        ]]
    }
    return ["ok": true, "action": action, "point": ["x": x, "y": y]]
}

func performFromStdin() -> [String: Any] {
    do {
        let data = FileHandle.standardInput.readDataToEndOfFile()
        let object = try JSONSerialization.jsonObject(with: data)
        guard let request = object as? [String: Any] else {
            throw NSError(domain: "MosaelWindowTools", code: 400, userInfo: [NSLocalizedDescriptionKey: "perform needs a JSON object"])
        }
        return try performAction(request)
    } catch {
        return ["error": ["message": String(describing: error)]]
    }
}

let arguments = CommandLine.arguments
if arguments.count < 2 {
    FileHandle.standardError.write(Data("usage: macos-window-tools windows | permissions | request-permission <accessibility|screen> | ax <pid> | perform\n".utf8))
    exit(2)
}

switch arguments[1] {
case "windows":
    WindowJSON.write(listWindows())
case "permissions":
    WindowJSON.write(permissionStatus())
case "request-permission":
    guard arguments.count >= 3 else {
        FileHandle.standardError.write(Data("request-permission needs accessibility or screen\n".utf8))
        exit(2)
    }
    WindowJSON.write(["granted": requestPermission(arguments[2])])
case "ax":
    guard arguments.count >= 3, let pid = Int32(arguments[2]) else {
        FileHandle.standardError.write(Data("ax needs a numeric pid\n".utf8))
        exit(2)
    }
    WindowJSON.write(accessibilityTree(pid))
case "perform":
    WindowJSON.write(performFromStdin())
default:
    FileHandle.standardError.write(Data("unknown subcommand: \(arguments[1])\n".utf8))
    exit(2)
}
